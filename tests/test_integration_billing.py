"""Интеграционные тесты биллинга (Phase 6) на реальном PostgreSQL.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.database import build_engine, build_session_factory
from app.database.models import (
    Appointment,
    AppointmentStatus,
    AuditLogEntry,
    Barber,
    BarberBranch,
    Branch,
    Feature,
    LimitKey,
    Plan,
    PlanFeature,
    PlanLimit,
    Role,
    Service,
    StaffMember,
    Subscription,
    SubscriptionStatus,
    Tenant,
    User,
    WorkingSchedule,
)
from app.database.repositories import PlanRepository, StaffRepository, SubscriptionRepository
from app.services.billing import (
    DEFAULT_PLAN_CODE,
    LEGACY_PLAN_CODE,
    EntitlementService,
    FeatureNotAvailable,
    LimitService,
    PlanLimitExceeded,
    SubscriptionService,
    is_effectively_active,
)
from app.services.booking import BookingService
from app.services.onboarding import TenantOnboardingService
from app.services.provisioning import (
    BarberProvisioningService,
    BranchProvisioningService,
    ServiceProvisioningService,
)
from app.services.staff import StaffService
from app.utils.dt import combine_local, now_utc

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — интеграционные тесты пропущены"
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
        ADMIN_ID="111111",
        TIMEZONE="Europe/Chisinau",
    )


@pytest.fixture
async def engine(settings: Settings):
    engine = build_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return build_session_factory(engine)


@pytest.fixture
async def tenant_id(session_factory):
    """Арендатор без подписки — как у любого до Phase 6 (fail-open путь)."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        tenant = Tenant(name=f"Test Tenant {marker}", slug=f"test-{marker}")
        session.add(tenant)
        await session.commit()
        tid = tenant.id
    yield tid
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tid))
        await session.commit()


@pytest.fixture
async def onboarding_tenant(session_factory):
    """Арендатор, созданный через TenantOnboardingService — с Phase 6 сразу
    получает Subscription(FREE, ACTIVE)."""
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session,
            name="New Shop",
            slug=f"new-{uuid.uuid4().hex[:8]}",
            timezone="Europe/Chisinau",
            currency="MDL",
        )
        tid = tenant.id
    yield tid
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tid))
        await session.commit()


@pytest.fixture
async def fixtures(session_factory, tenant_id):
    """Филиал, барбер (работает всю неделю 10:00-19:00), услуга и клиент —
    та же форма, что tests/test_integration_booking.py::fixtures."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        branch = Branch(tenant_id=tenant_id, name=f"Тест-филиал {marker}")
        barber = Barber(tenant_id=tenant_id, name=f"Тест-барбер {marker}")
        service = Service(
            tenant_id=tenant_id,
            name=f"Тест-услуга {marker}",
            duration_minutes=60,
            price=Decimal("250.00"),
        )
        user = User(
            tenant_id=tenant_id,
            telegram_id=900_000_000 + int(marker, 16) % 1_000_000,
            full_name="Тест Клиент",
        )
        session.add_all([branch, barber, service, user])
        await session.flush()
        session.add(BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch.id))
        for weekday in range(7):
            session.add(
                WorkingSchedule(
                    tenant_id=tenant_id,
                    barber_id=barber.id,
                    branch_id=branch.id,
                    weekday=weekday,
                    start_time=time(10, 0),
                    end_time=time(19, 0),
                )
            )
        await session.commit()
        ids = (barber.id, service.id, user.id, branch.id)
    yield ids
    async with session_factory() as session:
        await session.execute(delete(Appointment).where(Appointment.barber_id == ids[0]))
        await session.execute(delete(WorkingSchedule).where(WorkingSchedule.barber_id == ids[0]))
        await session.execute(delete(BarberBranch).where(BarberBranch.barber_id == ids[0]))
        await session.execute(delete(Barber).where(Barber.id == ids[0]))
        await session.execute(delete(Service).where(Service.id == ids[1]))
        await session.execute(delete(User).where(User.id == ids[2]))
        await session.execute(delete(Branch).where(Branch.id == ids[3]))
        await session.commit()


async def _load_user(session, user_id: uuid.UUID) -> User:
    return await session.get(User, user_id)


def target_slot(settings: Settings, *, days_ahead: int = 2, hour: int = 12):
    day = (now_utc().astimezone(settings.tz) + timedelta(days=days_ahead)).date()
    return combine_local(day, time(hour, 0), settings.tz)


async def _attach_plan(session_factory, tenant_id, *, feature_limits: dict, features=()):
    """Заводит тестовый Plan с заданными лимитами/фичами и подписывает на
    него арендатора — для тестов, которым нужен лимит меньше боевого FREE."""
    async with session_factory() as session:
        plan = Plan(
            code=f"test-{uuid.uuid4().hex[:8]}",
            name="Test Plan",
            is_active=True,
            features=[PlanFeature(feature=f) for f in features],
            limits=[PlanLimit(limit_key=k, value=v) for k, v in feature_limits.items()],
        )
        session.add(plan)
        await session.flush()
        await SubscriptionRepository(session, tenant_id).create(
            plan_id=plan.id, status=SubscriptionStatus.ACTIVE, current_period_start=now_utc()
        )
        await session.commit()
        return plan.id


# === A. PLAN: каталог тарифов ================================================
async def test_seeded_plans_exist_with_expected_codes(session_factory):
    async with session_factory() as session:
        repo = PlanRepository(session)
        free = await repo.get_by_code("free")
        pro = await repo.get_by_code("pro")
        legacy = await repo.get_by_code("legacy")
    assert free is not None and free.name
    assert pro is not None
    assert legacy is not None


async def test_free_plan_has_expected_limits_and_features(session_factory):
    async with session_factory() as session:
        plan = await PlanRepository(session).get_by_code(DEFAULT_PLAN_CODE)
        limits = {limit.limit_key: limit.value for limit in plan.limits}
        features = {f.feature for f in plan.features}
    assert limits[LimitKey.MAX_BRANCHES] == 1
    assert limits[LimitKey.MAX_BARBERS] == 2
    assert limits[LimitKey.MAX_STAFF] == 3
    assert limits[LimitKey.MAX_SERVICES] == 10
    assert limits[LimitKey.MAX_MONTHLY_APPOINTMENTS] == 100
    assert features == {Feature.BASIC_BOOKING, Feature.REMINDERS}


async def test_pro_plan_is_unlimited_with_all_features(session_factory):
    async with session_factory() as session:
        plan = await PlanRepository(session).get_by_code("pro")
        limits = {limit.limit_key: limit.value for limit in plan.limits}
        features = {f.feature for f in plan.features}
    assert all(value is None for value in limits.values())
    assert features == set(Feature)


async def test_legacy_plan_is_inactive_and_unlimited(session_factory):
    async with session_factory() as session:
        plan = await PlanRepository(session).get_by_code(LEGACY_PLAN_CODE)
        limits = {limit.limit_key: limit.value for limit in plan.limits}
    assert plan.is_active is False
    assert all(value is None for value in limits.values())


async def test_list_active_excludes_legacy(session_factory):
    async with session_factory() as session:
        codes = {p.code for p in await PlanRepository(session).list_active()}
    assert LEGACY_PLAN_CODE not in codes
    assert {DEFAULT_PLAN_CODE, "pro"} <= codes


async def test_list_all_includes_legacy(session_factory):
    async with session_factory() as session:
        codes = {p.code for p in await PlanRepository(session).list_all()}
    assert LEGACY_PLAN_CODE in codes


# === B. SUBSCRIPTION: жизненный цикл =========================================
async def test_onboarding_tenant_gets_free_subscription_automatically(
    session_factory, onboarding_tenant
):
    async with session_factory() as session:
        subscription = await SubscriptionRepository(session, onboarding_tenant).get()
    assert subscription is not None
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.plan.code == DEFAULT_PLAN_CODE


async def test_raw_tenant_has_no_subscription_by_default(session_factory, tenant_id):
    async with session_factory() as session:
        subscription = await SubscriptionRepository(session, tenant_id).get()
    assert subscription is None


async def test_only_one_subscription_per_tenant(session_factory, onboarding_tenant):
    async with session_factory() as session:
        plan = await PlanRepository(session).get_by_code("pro")
        session.add(
            Subscription(
                tenant_id=onboarding_tenant, plan_id=plan.id, status=SubscriptionStatus.ACTIVE
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_get_or_create_default_creates_free_subscription_if_missing(
    session_factory, tenant_id
):
    async with session_factory() as session:
        subscription = await SubscriptionService(session, tenant_id).get_or_create_default()
    assert subscription.plan.code == DEFAULT_PLAN_CODE
    assert subscription.status == SubscriptionStatus.ACTIVE


async def test_get_or_create_default_is_idempotent(session_factory, tenant_id):
    async with session_factory() as session:
        first = await SubscriptionService(session, tenant_id).get_or_create_default()
        first_id = first.id
    async with session_factory() as session:
        second = await SubscriptionService(session, tenant_id).get_or_create_default()
    assert second.id == first_id


async def test_change_plan_switches_plan_and_writes_audit_log(session_factory, onboarding_tenant):
    async with session_factory() as session:
        subscription = await SubscriptionService(session, onboarding_tenant).change_plan(
            plan_code="pro", actor_telegram_id=42
        )
    assert subscription.plan.code == "pro"

    async with session_factory() as session:
        entry = await session.scalar(
            select(AuditLogEntry).where(
                AuditLogEntry.tenant_id == onboarding_tenant,
                AuditLogEntry.action == "subscription.plan_changed",
            )
        )
    assert entry is not None
    assert entry.actor_telegram_id == 42
    assert entry.details["new_plan_id"] == str(subscription.plan_id)


async def test_change_plan_rejects_unknown_code(session_factory, onboarding_tenant):
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await SubscriptionService(session, onboarding_tenant).change_plan(
                plan_code="does-not-exist", actor_telegram_id=42
            )


# === C. is_effectively_active: чистая функция (без БД) =======================
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (SubscriptionStatus.TRIALING, True),
        (SubscriptionStatus.ACTIVE, True),
        (SubscriptionStatus.PAST_DUE, True),
        (SubscriptionStatus.CANCELED, False),
        (SubscriptionStatus.EXPIRED, False),
    ],
)
def test_is_effectively_active_truth_table(status, expected):
    assert is_effectively_active(status) is expected


# === D. FEATURES: entitlement ==================================================
async def test_has_feature_true_for_feature_on_plan(session_factory, onboarding_tenant):
    async with session_factory() as session:
        has = await EntitlementService(session, onboarding_tenant).has_feature(Feature.REMINDERS)
    assert has is True


async def test_has_feature_false_for_feature_not_on_plan(session_factory, onboarding_tenant):
    async with session_factory() as session:
        has = await EntitlementService(session, onboarding_tenant).has_feature(Feature.ANALYTICS)
    assert has is False


async def test_has_feature_fails_open_without_subscription(session_factory, tenant_id):
    async with session_factory() as session:
        has = await EntitlementService(session, tenant_id).has_feature(Feature.ANALYTICS)
    assert has is True


async def test_require_feature_raises_feature_not_available(session_factory, onboarding_tenant):
    async with session_factory() as session:
        with pytest.raises(FeatureNotAvailable) as excinfo:
            await EntitlementService(session, onboarding_tenant).require_feature(
                Feature.CSV_EXPORT
            )
    assert excinfo.value.feature == Feature.CSV_EXPORT
    assert excinfo.value.key == "billing.feature_not_available"


async def test_entitlements_are_tenant_isolated(session_factory, onboarding_tenant, tenant_id):
    async with session_factory() as session:
        await SubscriptionService(session, onboarding_tenant).change_plan(
            plan_code="pro", actor_telegram_id=1
        )
    async with session_factory() as session:
        await SubscriptionRepository(session, tenant_id).create(
            plan_id=(await PlanRepository(session).get_by_code(DEFAULT_PLAN_CODE)).id,
            status=SubscriptionStatus.ACTIVE,
        )
        await session.commit()

    async with session_factory() as session:
        pro_tenant_has_analytics = await EntitlementService(
            session, onboarding_tenant
        ).has_feature(Feature.ANALYTICS)
        free_tenant_has_analytics = await EntitlementService(session, tenant_id).has_feature(
            Feature.ANALYTICS
        )
    assert pro_tenant_has_analytics is True
    assert free_tenant_has_analytics is False


# === E. LIMITS: usage и get_limit ==============================================
async def test_get_limit_returns_none_without_subscription(session_factory, tenant_id):
    async with session_factory() as session:
        limit = await LimitService(session, tenant_id).get_limit(LimitKey.MAX_BRANCHES)
    assert limit is None


async def test_get_limit_returns_none_for_unlimited_plan_value(session_factory, onboarding_tenant):
    async with session_factory() as session:
        await SubscriptionService(session, onboarding_tenant).change_plan(
            plan_code="pro", actor_telegram_id=1
        )
    async with session_factory() as session:
        limit = await LimitService(session, onboarding_tenant).get_limit(LimitKey.MAX_BRANCHES)
    assert limit is None


async def test_get_limit_returns_plan_value(session_factory, onboarding_tenant):
    async with session_factory() as session:
        limit = await LimitService(session, onboarding_tenant).get_limit(LimitKey.MAX_BRANCHES)
    assert limit == 1


async def test_get_usage_max_branches_counts_active_only(session_factory, onboarding_tenant):
    async with session_factory() as session:
        session.add_all(
            [
                Branch(tenant_id=onboarding_tenant, name="Активный"),
                Branch(tenant_id=onboarding_tenant, name="Скрытый", is_active=False),
            ]
        )
        await session.commit()
    async with session_factory() as session:
        usage = await LimitService(session, onboarding_tenant).get_usage(LimitKey.MAX_BRANCHES)
    assert usage == 1


async def test_get_usage_max_barbers_counts_only_bookable(session_factory, onboarding_tenant):
    async with session_factory() as session:
        branch = Branch(tenant_id=onboarding_tenant, name="Филиал")
        linked = Barber(tenant_id=onboarding_tenant, name="Привязан")
        unlinked = Barber(tenant_id=onboarding_tenant, name="Не привязан")
        session.add_all([branch, linked, unlinked])
        await session.flush()
        session.add(
            BarberBranch(tenant_id=onboarding_tenant, barber_id=linked.id, branch_id=branch.id)
        )
        await session.commit()
    async with session_factory() as session:
        usage = await LimitService(session, onboarding_tenant).get_usage(LimitKey.MAX_BARBERS)
    assert usage == 1


async def test_get_usage_max_staff_counts_active_staff(session_factory, onboarding_tenant):
    async with session_factory() as session:
        usage_before = await LimitService(session, onboarding_tenant).get_usage(
            LimitKey.MAX_STAFF
        )
        await StaffRepository(session, onboarding_tenant).create(
            telegram_id=555_001, role=Role.MANAGER
        )
        await session.commit()
    async with session_factory() as session:
        usage_after = await LimitService(session, onboarding_tenant).get_usage(LimitKey.MAX_STAFF)
    assert usage_after == usage_before + 1


async def test_get_usage_max_services_counts_active_only(session_factory, onboarding_tenant):
    async with session_factory() as session:
        session.add(
            Service(
                tenant_id=onboarding_tenant,
                name="Услуга",
                duration_minutes=30,
                price=Decimal("100"),
            )
        )
        await session.commit()
    async with session_factory() as session:
        usage = await LimitService(session, onboarding_tenant).get_usage(LimitKey.MAX_SERVICES)
    assert usage == 1


async def test_get_usage_max_monthly_appointments_excludes_cancelled_and_no_show(
    session_factory, onboarding_tenant, fixtures
):
    barber_id, service_id, user_id, branch_id = fixtures
    start = now_utc().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    async with session_factory() as session:
        rows = [
            Appointment(
                tenant_id=onboarding_tenant,
                branch_id=branch_id,
                user_id=user_id,
                barber_id=barber_id,
                service_id=service_id,
                starts_at=start + timedelta(hours=i),
                ends_at=start + timedelta(hours=i, minutes=30),
                status=status,
                price=Decimal("100"),
                duration_minutes=30,
            )
            for i, status in enumerate(
                (
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.COMPLETED,
                    AppointmentStatus.CANCELLED,
                    AppointmentStatus.NO_SHOW,
                )
            )
        ]
        session.add_all(rows)
        await session.commit()
    async with session_factory() as session:
        usage = await LimitService(session, onboarding_tenant).get_usage(
            LimitKey.MAX_MONTHLY_APPOINTMENTS
        )
    assert usage == 2


# === F. ENFORCEMENT: лимиты применяются на границе сервисного слоя ==========
async def test_branch_provisioning_denied_past_free_plan_limit(session_factory, onboarding_tenant):
    async with session_factory() as session:
        await BranchProvisioningService(session, onboarding_tenant).create_branch(name="Первый")
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(PlanLimitExceeded) as excinfo:
            await BranchProvisioningService(session, onboarding_tenant).create_branch(
                name="Второй"
            )
    assert excinfo.value.limit_key == LimitKey.MAX_BRANCHES
    assert excinfo.value.maximum == 1


async def test_barber_provisioning_denied_past_free_plan_limit(session_factory, onboarding_tenant):
    async with session_factory() as session:
        branch = Branch(tenant_id=onboarding_tenant, name="Филиал")
        session.add(branch)
        await session.flush()
        branch_id = branch.id
        for i in range(2):
            barber = await BarberProvisioningService(session, onboarding_tenant).create_barber(
                name=f"Барбер {i}"
            )
            session.add(
                BarberBranch(tenant_id=onboarding_tenant, barber_id=barber.id, branch_id=branch_id)
            )
            await session.commit()
    async with session_factory() as session:
        with pytest.raises(PlanLimitExceeded) as excinfo:
            await BarberProvisioningService(session, onboarding_tenant).create_barber(
                name="Третий"
            )
    assert excinfo.value.limit_key == LimitKey.MAX_BARBERS


async def test_service_provisioning_denied_past_free_plan_limit(session_factory, onboarding_tenant):
    async with session_factory() as session:
        for i in range(10):
            await ServiceProvisioningService(session, onboarding_tenant).create_service(
                name=f"Услуга {i}", duration_minutes=30, price=Decimal("100")
            )
            await session.commit()
    async with session_factory() as session:
        with pytest.raises(PlanLimitExceeded) as excinfo:
            await ServiceProvisioningService(session, onboarding_tenant).create_service(
                name="Одиннадцатая", duration_minutes=30, price=Decimal("100")
            )
    assert excinfo.value.limit_key == LimitKey.MAX_SERVICES


async def test_staff_creation_denied_past_max_staff_limit(session_factory, onboarding_tenant):
    # У onboarding_tenant ещё нет владельца-сотрудника, лимит FREE = 3.
    async with session_factory() as session:
        for i in range(3):
            await StaffService(session, onboarding_tenant).create_staff(
                actor_telegram_id=1, telegram_id=600_000 + i, role=Role.MANAGER
            )
    async with session_factory() as session:
        with pytest.raises(PlanLimitExceeded) as excinfo:
            await StaffService(session, onboarding_tenant).create_staff(
                actor_telegram_id=1, telegram_id=600_999, role=Role.MANAGER
            )
    assert excinfo.value.limit_key == LimitKey.MAX_STAFF


async def test_monthly_appointment_limit_denies_nth_plus_one_booking(
    session_factory, fixtures, tenant_id, settings
):
    barber_id, service_id, user_id, branch_id = fixtures
    await _attach_plan(
        session_factory,
        tenant_id,
        feature_limits={LimitKey.MAX_MONTHLY_APPOINTMENTS: 2},
        features=(Feature.BASIC_BOOKING,),
    )

    async def attempt(hour: int) -> bool:
        async with session_factory() as session:
            user = await _load_user(session, user_id)
            try:
                await BookingService(session, settings, tenant_id).create_appointment(
                    user=user,
                    branch_id=branch_id,
                    barber_id=barber_id,
                    service_id=service_id,
                    start=target_slot(settings, hour=hour),
                )
            except PlanLimitExceeded:
                return False
            return True

    first = await attempt(10)
    second = await attempt(11)
    third = await attempt(12)
    assert (first, second, third) == (True, True, False)


# === G. CONCURRENCY: лимит не пробивается гонкой ==============================
async def test_concurrent_branch_creation_respects_max_branches_limit(
    session_factory, onboarding_tenant
):
    async def attempt(name: str) -> bool:
        async with session_factory() as session:
            try:
                await BranchProvisioningService(session, onboarding_tenant).create_branch(
                    name=name
                )
                await session.commit()
            except PlanLimitExceeded:
                return False
            return True

    results = await asyncio.gather(attempt("Гонка А"), attempt("Гонка Б"))
    assert sorted(results) == [False, True]

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Branch).where(Branch.tenant_id == onboarding_tenant)
        )
    assert count == 1


async def test_concurrent_monthly_appointment_creation_respects_limit(
    session_factory, fixtures, tenant_id, settings
):
    barber_id, service_id, _shared_user_id, branch_id = fixtures
    await _attach_plan(
        session_factory,
        tenant_id,
        feature_limits={LimitKey.MAX_MONTHLY_APPOINTMENTS: 3},
        features=(Feature.BASIC_BOOKING,),
    )
    hours = (10, 11, 12, 13, 14)
    # Разные клиенты на каждую попытку: иначе гонка упёрлась бы в
    # НЕСВЯЗАННЫЙ per-клиентский Settings.max_active_appointments (=3),
    # а не в проверяемый тарифный MAX_MONTHLY_APPOINTMENTS арендатора.
    async with session_factory() as session:
        user_ids = []
        for hour in hours:
            user = User(
                tenant_id=tenant_id,
                telegram_id=910_000_000 + hour,
                full_name=f"Клиент {hour}",
            )
            session.add(user)
            await session.flush()
            user_ids.append(user.id)
        await session.commit()

    async def attempt(hour: int, user_id: uuid.UUID) -> bool:
        async with session_factory() as session:
            user = await _load_user(session, user_id)
            try:
                await BookingService(session, settings, tenant_id).create_appointment(
                    user=user,
                    branch_id=branch_id,
                    barber_id=barber_id,
                    service_id=service_id,
                    start=target_slot(settings, hour=hour),
                )
            except PlanLimitExceeded:
                return False
            return True

    results = await asyncio.gather(
        *(attempt(hour, uid) for hour, uid in zip(hours, user_ids, strict=True))
    )
    assert sum(results) == 3


# === H. SECURITY / ИЗОЛЯЦИЯ АРЕНДАТОРОВ ========================================
async def test_subscription_repository_never_returns_other_tenants_row(
    session_factory, onboarding_tenant, tenant_id
):
    async with session_factory() as session:
        own = await SubscriptionRepository(session, onboarding_tenant).get()
        other = await SubscriptionRepository(session, tenant_id).get()
    assert own is not None
    assert other is None  # tenant_id не подписан — и уж точно не видит чужую подписку


async def test_limit_usage_never_leaks_across_tenants(session_factory, onboarding_tenant, tenant_id):
    async with session_factory() as session:
        session.add_all(
            [
                Branch(tenant_id=onboarding_tenant, name="A1"),
                Branch(tenant_id=onboarding_tenant, name="A2"),
            ]
        )
        await session.commit()
    async with session_factory() as session:
        usage_other = await LimitService(session, tenant_id).get_usage(LimitKey.MAX_BRANCHES)
    assert usage_other == 0


async def test_forged_plan_id_on_foreign_tenant_subscription_is_rejected(
    session_factory, onboarding_tenant
):
    """Нельзя обойти лимит, подсунув чужой/несуществующий plan_id напрямую —
    FK на plans.id физически не даст вставить мусорный идентификатор."""
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                Subscription.__table__.update()
                .where(Subscription.tenant_id == onboarding_tenant)
                .values(plan_id=uuid.uuid4())
            )
            await session.commit()


# === I. RBAC ===================================================================
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.TENANT_OWNER, True),
        (Role.TENANT_ADMIN, False),
        (Role.MANAGER, False),
        (Role.RECEPTIONIST, False),
        (Role.BARBER, False),
    ],
)
def test_manage_subscription_permission_matrix(role, expected):
    from app.database.models import Permission
    from app.services.authorization import AuthorizationService

    staff = StaffMember(tenant_id=uuid.uuid4(), telegram_id=1, role=role, is_active=True)
    assert (
        AuthorizationService.has_permission(staff, Permission.MANAGE_SUBSCRIPTION) is expected
    )


# === J. MIGRATION BACKFILL (поведение Legacy-тарифа) ===========================
async def test_legacy_plan_subscription_has_no_limits_and_all_features(
    session_factory, tenant_id
):
    """Симулирует состояние арендатора после бэкфилла миграции 0010."""
    async with session_factory() as session:
        legacy = await PlanRepository(session).get_by_code(LEGACY_PLAN_CODE)
        await SubscriptionRepository(session, tenant_id).create(
            plan_id=legacy.id, status=SubscriptionStatus.ACTIVE, current_period_start=now_utc()
        )
        await session.commit()

    async with session_factory() as session:
        limits = LimitService(session, tenant_id)
        entitlements = EntitlementService(session, tenant_id)
        for key in LimitKey:
            assert await limits.get_limit(key) is None
        for feature in Feature:
            assert await entitlements.has_feature(feature) is True


async def test_legacy_tenant_can_exceed_free_plan_branch_count(session_factory, tenant_id):
    """Арендатор «из прошлого» с 2 филиалами не должен упереться в потолок,
    которого не существовало на момент их создания (см. §7/§18 спецификации)."""
    async with session_factory() as session:
        legacy = await PlanRepository(session).get_by_code(LEGACY_PLAN_CODE)
        await SubscriptionRepository(session, tenant_id).create(
            plan_id=legacy.id, status=SubscriptionStatus.ACTIVE, current_period_start=now_utc()
        )
        await session.commit()

    async with session_factory() as session:
        await BranchProvisioningService(session, tenant_id).create_branch(name="Первый")
        await session.commit()
    async with session_factory() as session:
        await BranchProvisioningService(session, tenant_id).create_branch(name="Второй")
        await session.commit()
    async with session_factory() as session:
        third = await BranchProvisioningService(session, tenant_id).create_branch(name="Третий")
        await session.commit()
    assert third.name == "Третий"


# === K. REGRESSION: обычное бронирование не ломается на Legacy-тарифе ========
async def test_booking_flow_unaffected_on_legacy_plan(session_factory, fixtures, tenant_id, settings):
    barber_id, service_id, user_id, branch_id = fixtures
    async with session_factory() as session:
        legacy = await PlanRepository(session).get_by_code(LEGACY_PLAN_CODE)
        await SubscriptionRepository(session, tenant_id).create(
            plan_id=legacy.id, status=SubscriptionStatus.ACTIVE, current_period_start=now_utc()
        )
        await session.commit()

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=user,
            branch_id=branch_id,
            barber_id=barber_id,
            service_id=service_id,
            start=target_slot(settings, hour=15),
        )
    assert appointment.status == AppointmentStatus.CONFIRMED
