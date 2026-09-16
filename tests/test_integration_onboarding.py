"""Интеграционные тесты онбординга арендатора (Phase 5) на реальном
PostgreSQL.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.bot.states import OnboardingSG
from app.config import Settings
from app.database import build_engine, build_session_factory
from app.database.models import (
    AppointmentStatus,
    AuditLogEntry,
    Barber,
    BarberBranch,
    BarberService,
    Branch,
    BranchService,
    CancelledBy,
    Role,
    Service,
    StaffMember,
    TelegramBotIdentity,
    Tenant,
    TenantStatus,
    User,
    WorkingSchedule,
)
from app.database.repositories import (
    BarberRepository,
    BarberServiceRepository,
    BranchRepository,
    ScheduleRepository,
    ServiceRepository,
    StaffRepository,
    TenantRepository,
)
from app.services.booking import BookingError, BookingService
from app.services.onboarding import TenantOnboardingService
from app.services.schedule import ScheduleService
from app.utils.dt import combine_local, now_utc
from tests.conftest import MockedSession

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — интеграционные тесты пропущены"
)

ADMIN_TELEGRAM_ID = 700_001


@pytest.fixture
def settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
        ADMIN_ID=str(ADMIN_TELEGRAM_ID),
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
async def onboarding_tenant(session_factory):
    """Свежий арендатор в статусе ONBOARDING — ровно то, что создаёт
    TenantOnboardingService.create_tenant."""
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


def target_slot(settings: Settings, *, days_ahead: int = 2, hour: int = 12):
    day = (now_utc().astimezone(settings.tz) + timedelta(days=days_ahead)).date()
    return combine_local(day, time(hour, 0), settings.tz)


# --- A. Жизненный цикл арендатора --------------------------------------------
async def test_create_tenant_starts_in_onboarding(session_factory):
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name="Fresh Shop", slug=f"fresh-{uuid.uuid4().hex[:8]}"
        )
        tenant_id = tenant.id
        assert tenant.status == TenantStatus.ONBOARDING

    try:
        async with session_factory() as session:
            reloaded = await TenantRepository(session).get(tenant_id)
            assert reloaded.status == TenantStatus.ONBOARDING
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()


async def test_activate_fails_when_not_ready(session_factory, onboarding_tenant):
    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, onboarding_tenant).activate(
            actor_telegram_id=ADMIN_TELEGRAM_ID
        )
        assert readiness.is_ready is False
        assert "onboarding.missing_branch" in readiness.missing

    async with session_factory() as session:
        tenant = await TenantRepository(session).get(onboarding_tenant)
        assert tenant.status == TenantStatus.ONBOARDING


async def test_activate_succeeds_once_fully_configured(session_factory, onboarding_tenant):
    await _fully_configure(session_factory, onboarding_tenant)

    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, onboarding_tenant).activate(
            actor_telegram_id=ADMIN_TELEGRAM_ID
        )
        assert readiness.is_ready is True

    async with session_factory() as session:
        tenant = await TenantRepository(session).get(onboarding_tenant)
        assert tenant.status == TenantStatus.ACTIVE
        audit = await session.scalar(
            select(AuditLogEntry).where(
                AuditLogEntry.tenant_id == onboarding_tenant,
                AuditLogEntry.action == "tenant.activated",
            )
        )
        assert audit is not None


async def test_activate_is_idempotent_on_already_active_tenant(session_factory, onboarding_tenant):
    await _fully_configure(session_factory, onboarding_tenant)
    async with session_factory() as session:
        await TenantOnboardingService(session, onboarding_tenant).activate(
            actor_telegram_id=ADMIN_TELEGRAM_ID
        )

    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, onboarding_tenant).activate(
            actor_telegram_id=ADMIN_TELEGRAM_ID
        )
        assert readiness.is_ready is True

    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(AuditLogEntry).where(
                    AuditLogEntry.tenant_id == onboarding_tenant,
                    AuditLogEntry.action == "tenant.activated",
                )
            )
        )
        assert len(rows) == 1, "повторная активация не должна писать второй audit-лог"


# --- B. Владелец --------------------------------------------------------------
async def test_ensure_owner_creates_tenant_owner(session_factory, onboarding_tenant):
    async with session_factory() as session:
        staff = await TenantOnboardingService(session, onboarding_tenant).ensure_owner(
            telegram_id=ADMIN_TELEGRAM_ID, actor_telegram_id=ADMIN_TELEGRAM_ID
        )
        assert staff.role == Role.TENANT_OWNER
        assert staff.tenant_id == onboarding_tenant


async def test_ensure_owner_is_idempotent_on_repeat_call(session_factory, onboarding_tenant):
    async with session_factory() as session:
        first = await TenantOnboardingService(session, onboarding_tenant).ensure_owner(
            telegram_id=ADMIN_TELEGRAM_ID, actor_telegram_id=ADMIN_TELEGRAM_ID
        )
    async with session_factory() as session:
        second = await TenantOnboardingService(session, onboarding_tenant).ensure_owner(
            telegram_id=ADMIN_TELEGRAM_ID, actor_telegram_id=ADMIN_TELEGRAM_ID
        )
        assert second.id == first.id

    async with session_factory() as session:
        owners = list(
            await session.scalars(
                select(StaffMember).where(
                    StaffMember.tenant_id == onboarding_tenant,
                    StaffMember.role == Role.TENANT_OWNER,
                )
            )
        )
        assert len(owners) == 1


async def test_duplicate_owner_is_rejected_by_database_constraint(session_factory, onboarding_tenant):
    """Прямой обход сервиса (INSERT в обход ensure_owner) должен упереться в
    частичный уникальный индекс uq_staff_members_tenant_id_owner (миграция 0009)."""
    async with session_factory() as session:
        session.add(
            StaffMember(tenant_id=onboarding_tenant, telegram_id=1, role=Role.TENANT_OWNER)
        )
        await session.commit()

    async with session_factory() as session:
        session.add(
            StaffMember(tenant_id=onboarding_tenant, telegram_id=2, role=Role.TENANT_OWNER)
        )
        with pytest.raises(IntegrityError) as error:
            await session.flush()
        assert "uq_staff_members_tenant_id_owner" in str(error.value.orig)
        await session.rollback()


async def test_owner_belongs_to_correct_tenant(session_factory):
    async with session_factory() as session:
        tenant_a = await TenantOnboardingService.create_tenant(
            session, name="A", slug=f"a-{uuid.uuid4().hex[:8]}"
        )
        tenant_b = await TenantOnboardingService.create_tenant(
            session, name="B", slug=f"b-{uuid.uuid4().hex[:8]}"
        )
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id

    try:
        async with session_factory() as session:
            await TenantOnboardingService(session, tenant_a_id).ensure_owner(
                telegram_id=ADMIN_TELEGRAM_ID, actor_telegram_id=ADMIN_TELEGRAM_ID
            )

        async with session_factory() as session:
            owner_a = await StaffRepository(session, tenant_a_id).get_owner()
            owner_b = await StaffRepository(session, tenant_b_id).get_owner()
            assert owner_a is not None
            assert owner_b is None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id))))
            await session.commit()


# --- C. Филиал ----------------------------------------------------------------
async def test_create_first_branch_uses_tenant_defaults(session_factory, onboarding_tenant):
    async with session_factory() as session:
        branch = await BranchRepository(session, onboarding_tenant).create(name="Main")
        await session.commit()
        assert branch.timezone == "Europe/Chisinau"
        assert branch.currency == "MDL"


async def test_branch_created_during_onboarding_is_tenant_isolated(session_factory, onboarding_tenant):
    async with session_factory() as session:
        other = await TenantOnboardingService.create_tenant(
            session, name="Other", slug=f"o-{uuid.uuid4().hex[:8]}"
        )
        other_id = other.id

    try:
        async with session_factory() as session:
            branch = await BranchRepository(session, onboarding_tenant).create(name="Main")
            branch_id = branch.id
            await session.commit()

        async with session_factory() as session:
            # IDOR: чужой tenant_id не видит филиал даже по точному UUID.
            assert await BranchRepository(session, other_id).get(branch_id) is None
            assert await BranchRepository(session, onboarding_tenant).get(branch_id) is not None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == other_id))
            await session.commit()


# --- C2. Онбординг через BranchProvisioningService (Phase 9B §M-5) ---------
# set_branch_currency теперь создаёт первый филиал через
# BranchProvisioningService (единая точка проверки MAX_BRANCHES), а не через
# голый BranchRepository — проверяем это через реальный Dispatcher, а не
# только вызовом сервиса напрямую (это уже покрыто test_integration_billing.py).
async def _bind_bot(session_factory, tenant_id: uuid.UUID, bot_id: int) -> None:
    async with session_factory() as session:
        session.add(
            TelegramBotIdentity(tenant_id=tenant_id, telegram_bot_id=bot_id, username="ob_bot")
        )
        await session.commit()


async def _seed_branch_currency_state(
    dispatcher, bot: Bot, user_id: int, *, branch_name: str, branch_timezone: str | None
) -> None:
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    state = FSMContext(storage=dispatcher.storage, key=key)
    await state.set_state(OnboardingSG.branch_currency)
    await state.update_data(branch_name=branch_name, branch_timezone=branch_timezone)


def _bot(bot_id: int) -> Bot:
    bot = Bot(token=f"{bot_id}:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw", session=MockedSession())
    bot.calls = bot.session.calls
    return bot


def _make_message(text: str, user_id: int) -> Message:
    return Message(
        message_id=1, date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
    )


async def _feed(dispatcher, bot: Bot, message: Message) -> list[tuple[str, str | None]]:
    bot.calls.clear()
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))
    return list(bot.calls)


_next_ob_bot_id = iter(range(950_000_001, 950_100_000))


async def test_onboarding_creates_first_branch_via_provisioning_service(
    flow_dispatcher, flow_session_factory
):
    tenant_id = None
    async with flow_session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name="Prov Tenant", slug=f"prov-{uuid.uuid4().hex[:8]}"
        )
        tenant_id = tenant.id
    bot_id = next(_next_ob_bot_id)
    await _bind_bot(flow_session_factory, tenant_id, bot_id)
    user_id = 700_900_001
    bot = _bot(bot_id)
    try:
        await _seed_branch_currency_state(
            flow_dispatcher, bot, user_id, branch_name="Main", branch_timezone=None
        )
        calls = await _feed(flow_dispatcher, bot, _make_message("-", user_id))
        assert any("услуг" in (text or "").lower() for _, text in calls)

        async with flow_session_factory() as session:
            branches = await BranchRepository(session, tenant_id).list_active()
        assert len(branches) == 1
        assert branches[0].name == "Main"
    finally:
        async with flow_session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()


async def test_onboarding_branch_creation_respects_max_branches_limit(
    flow_dispatcher, flow_session_factory
):
    """Если к моменту этого шага у арендатора уже есть филиал на пределе
    лимита тарифа (Free: MAX_BRANCHES=1) — второй не должен молча
    создаться в обход лимита."""
    async with flow_session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name="AtLimit Tenant", slug=f"atlimit-{uuid.uuid4().hex[:8]}"
        )
        tenant_id = tenant.id
        # Уже есть 1 активный филиал — Free-план это исчерпывает.
        await BranchRepository(session, tenant_id).create(name="Existing")
        await session.commit()

    bot_id = next(_next_ob_bot_id)
    await _bind_bot(flow_session_factory, tenant_id, bot_id)
    user_id = 700_900_002
    bot = _bot(bot_id)
    try:
        await _seed_branch_currency_state(
            flow_dispatcher, bot, user_id, branch_name="Second", branch_timezone=None
        )
        calls = await _feed(flow_dispatcher, bot, _make_message("-", user_id))
        assert any("лимит" in (text or "").lower() for _, text in calls)

        async with flow_session_factory() as session:
            branches = await BranchRepository(session, tenant_id).list_active()
        # Всё ещё ровно один филиал — второй не создан в обход лимита.
        assert len(branches) == 1
        assert branches[0].name == "Existing"
    finally:
        async with flow_session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()


async def test_onboarding_branch_creation_is_tenant_isolated_under_dispatcher(
    flow_dispatcher, flow_session_factory
):
    """Арендатор A на пределе лимита не мешает арендатору B создать свой
    первый филиал через тот же обработчик."""
    async with flow_session_factory() as session:
        tenant_a = await TenantOnboardingService.create_tenant(
            session, name="A", slug=f"a-{uuid.uuid4().hex[:8]}"
        )
        tenant_a_id = tenant_a.id
        await BranchRepository(session, tenant_a_id).create(name="A-Existing")
        tenant_b = await TenantOnboardingService.create_tenant(
            session, name="B", slug=f"b-{uuid.uuid4().hex[:8]}"
        )
        tenant_b_id = tenant_b.id
        await session.commit()

    bot_a_id, bot_b_id = next(_next_ob_bot_id), next(_next_ob_bot_id)
    await _bind_bot(flow_session_factory, tenant_a_id, bot_a_id)
    await _bind_bot(flow_session_factory, tenant_b_id, bot_b_id)
    user_id = 700_900_003
    bot_b = _bot(bot_b_id)
    try:
        await _seed_branch_currency_state(
            flow_dispatcher, bot_b, user_id, branch_name="B-Main", branch_timezone=None
        )
        calls = await _feed(flow_dispatcher, bot_b, _make_message("-", user_id))
        assert not any("лимит" in (text or "").lower() for _, text in calls)

        async with flow_session_factory() as session:
            branches_b = await BranchRepository(session, tenant_b_id).list_active()
        assert len(branches_b) == 1
        assert branches_b[0].name == "B-Main"
    finally:
        async with flow_session_factory() as session:
            await session.execute(
                delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
            )
            await session.commit()


async def test_onboarding_branch_creation_no_duplicate_on_retry(
    flow_dispatcher, flow_session_factory
):
    """После успешного создания первого филиала состояние уходит с
    branch_currency (на следующий шаг мастера) — повторная отправка того же
    сообщения не должна создать второй филиал."""
    async with flow_session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name="Retry Tenant", slug=f"retry-{uuid.uuid4().hex[:8]}"
        )
        tenant_id = tenant.id
    bot_id = next(_next_ob_bot_id)
    await _bind_bot(flow_session_factory, tenant_id, bot_id)
    user_id = 700_900_004
    bot = _bot(bot_id)
    try:
        await _seed_branch_currency_state(
            flow_dispatcher, bot, user_id, branch_name="Once", branch_timezone=None
        )
        await _feed(flow_dispatcher, bot, _make_message("-", user_id))
        # Повторная отправка того же текста: состояние уже не branch_currency,
        # поэтому попадает в другой хендлер (следующий шаг мастера), а не
        # создаёт второй филиал.
        await _feed(flow_dispatcher, bot, _make_message("-", user_id))

        async with flow_session_factory() as session:
            branches = await BranchRepository(session, tenant_id).list_active()
        assert len(branches) == 1
    finally:
        async with flow_session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()


# --- D. Услуги ------------------------------------------------------------
async def test_service_created_during_onboarding_is_available_at_branch_by_default(
    session_factory, onboarding_tenant
):
    async with session_factory() as session:
        branch = await BranchRepository(session, onboarding_tenant).create(name="Main")
        service = await ServiceRepository(session, onboarding_tenant).create(
            name="Cut", duration_minutes=30, price=Decimal("50"), currency=branch.currency
        )
        await session.commit()

    async with session_factory() as session:
        available = await BranchRepository(session, onboarding_tenant).service_available_at_branch(
            service_id=service.id, branch_id=branch.id
        )
        assert available is True


async def test_service_cannot_be_attached_to_another_tenants_branch(session_factory, onboarding_tenant):
    async with session_factory() as session:
        other = await TenantOnboardingService.create_tenant(
            session, name="Other", slug=f"o-{uuid.uuid4().hex[:8]}"
        )
        other_id = other.id

    try:
        async with session_factory() as session:
            own_service = await ServiceRepository(session, onboarding_tenant).create(
                name="Cut", duration_minutes=30, price=Decimal("50")
            )
            foreign_branch = await BranchRepository(session, other_id).create(name="Foreign")
            await session.commit()
            service_id, foreign_branch_id = own_service.id, foreign_branch.id

        async with session_factory() as session:
            # assign_service работает от имени own_tenant, но branch_id чужой —
            # guard должен вернуть None, а не создать межарендаторскую строку.
            link = await BranchRepository(session, onboarding_tenant).assign_service(
                service_id=service_id, branch_id=foreign_branch_id
            )
            assert link is None

        async with session_factory() as session:
            leaked = await session.scalar(
                select(BranchService).where(BranchService.service_id == service_id)
            )
            assert leaked is None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == other_id))
            await session.commit()


async def test_repeated_service_creation_with_same_name_is_rejected(session_factory, onboarding_tenant):
    async with session_factory() as session:
        await ServiceRepository(session, onboarding_tenant).create(
            name="Cut", duration_minutes=30, price=Decimal("50")
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(IntegrityError) as error:
            await ServiceRepository(session, onboarding_tenant).create(
                name="Cut", duration_minutes=45, price=Decimal("60")
            )
        assert "uq_services_tenant_id_name" in str(error.value.orig)
        await session.rollback()


# --- E. Барберы / персонал ----------------------------------------------------
async def test_barber_created_during_onboarding_is_assigned_to_branch(session_factory, onboarding_tenant):
    async with session_factory() as session:
        branch = await BranchRepository(session, onboarding_tenant).create(name="Main")
        barber = await BarberRepository(session, onboarding_tenant).create(name="Ion")
        await BranchRepository(session, onboarding_tenant).assign_barber(
            barber_id=barber.id, branch_id=branch.id
        )
        await session.commit()

    async with session_factory() as session:
        branches = await BranchRepository(session, onboarding_tenant).list_for_barber(barber.id)
        assert [b.id for b in branches] == [branch.id]


async def test_barber_can_be_assigned_to_multiple_branches_after_onboarding(
    session_factory, onboarding_tenant
):
    async with session_factory() as session:
        branch_a = await BranchRepository(session, onboarding_tenant).create(name="A")
        branch_b = await BranchRepository(session, onboarding_tenant).create(name="B")
        barber = await BarberRepository(session, onboarding_tenant).create(name="Ion")
        repo = BranchRepository(session, onboarding_tenant)
        await repo.assign_barber(barber_id=barber.id, branch_id=branch_a.id)
        await repo.assign_barber(barber_id=barber.id, branch_id=branch_b.id)
        await session.commit()

    async with session_factory() as session:
        branches = await BranchRepository(session, onboarding_tenant).list_for_barber(barber.id)
        assert {b.id for b in branches} == {branch_a.id, branch_b.id}


async def test_barber_assignment_rejects_cross_tenant_branch(session_factory, onboarding_tenant):
    async with session_factory() as session:
        other = await TenantOnboardingService.create_tenant(
            session, name="Other", slug=f"o-{uuid.uuid4().hex[:8]}"
        )
        other_id = other.id

    try:
        async with session_factory() as session:
            barber = await BarberRepository(session, onboarding_tenant).create(name="Ion")
            foreign_branch = await BranchRepository(session, other_id).create(name="Foreign")
            await session.commit()
            barber_id, foreign_branch_id = barber.id, foreign_branch.id

        async with session_factory() as session:
            link = await BranchRepository(session, onboarding_tenant).assign_barber(
                barber_id=barber_id, branch_id=foreign_branch_id
            )
            assert link is None

        async with session_factory() as session:
            leaked = await session.scalar(
                select(BarberBranch).where(BarberBranch.barber_id == barber_id)
            )
            assert leaked is None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == other_id))
            await session.commit()


# --- F. BarberService (opt-out) ----------------------------------------------
async def test_barber_provides_service_by_default_after_onboarding(session_factory, onboarding_tenant):
    async with session_factory() as session:
        barber = await BarberRepository(session, onboarding_tenant).create(name="Ion")
        service = await ServiceRepository(session, onboarding_tenant).create(
            name="Cut", duration_minutes=30, price=Decimal("50")
        )
        await session.commit()

    async with session_factory() as session:
        provides = await BarberServiceRepository(session, onboarding_tenant).barber_provides_service(
            barber_id=barber.id, service_id=service.id
        )
        assert provides is True


async def test_onboarding_does_not_create_barber_service_rows(session_factory, onboarding_tenant):
    """Онбординг не должен создавать явные BarberService при заведении
    барбера/услуги — opt-out по умолчанию делает это ненужным
    (см. docs/TENANT_ONBOARDING_DESIGN.md §7)."""
    async with session_factory() as session:
        barber = await BarberRepository(session, onboarding_tenant).create(name="Ion")
        await ServiceRepository(session, onboarding_tenant).create(
            name="Cut", duration_minutes=30, price=Decimal("50")
        )
        await session.commit()

    async with session_factory() as session:
        rows = await session.scalar(
            select(BarberService.id).where(BarberService.barber_id == barber.id)
        )
        assert rows is None


async def test_booking_respects_explicit_barber_service_optout(session_factory, settings, onboarding_tenant):
    tenant_id = onboarding_tenant
    async with session_factory() as session:
        branch = await BranchRepository(session, tenant_id).create(name="Main")
        barber = await BarberRepository(session, tenant_id).create(name="Ion")
        await BranchRepository(session, tenant_id).assign_barber(
            barber_id=barber.id, branch_id=branch.id
        )
        service = await ServiceRepository(session, tenant_id).create(
            name="Cut", duration_minutes=30, price=Decimal("50")
        )
        for weekday in range(7):
            session.add(
                WorkingSchedule(
                    tenant_id=tenant_id,
                    barber_id=barber.id,
                    branch_id=branch.id,
                    weekday=weekday,
                    start_time=time(9, 0),
                    end_time=time(18, 0),
                )
            )
        user = User(tenant_id=tenant_id, telegram_id=800_500, full_name="Client")
        session.add(user)
        await BarberServiceRepository(session, tenant_id).set_active(
            barber_id=barber.id, service_id=service.id, is_active=False
        )
        await session.commit()
        branch_id, barber_id, service_id, user_id = branch.id, barber.id, service.id, user.id

    async with session_factory() as session:
        user_obj = await session.get(User, user_id)
        with pytest.raises(BookingError) as error:
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user_obj,
                branch_id=branch_id,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings),
            )
        assert error.value.key == "error.barber_not_provide_service"


# --- G. График ------------------------------------------------------------
async def test_onboarding_schedule_is_branch_timezone_aware(session_factory, settings, onboarding_tenant):
    tenant_id = onboarding_tenant
    async with session_factory() as session:
        branch = await BranchRepository(session, tenant_id).create(
            name="NY", timezone="America/New_York"
        )
        barber = await BarberRepository(session, tenant_id).create(name="Ion")
        await BranchRepository(session, tenant_id).assign_barber(
            barber_id=barber.id, branch_id=branch.id
        )
        schedule_repo = ScheduleRepository(session, tenant_id)
        for weekday in range(7):
            await schedule_repo.set_day(barber.id, branch.id, weekday, time(9, 0), time(17, 0))
        await session.commit()
        branch_id, barber_id = branch.id, barber.id

    async with session_factory() as session:
        branch_obj = await BranchRepository(session, tenant_id).get(branch_id)
        day = (now_utc().astimezone(branch_obj.tz) + timedelta(days=5)).date()
        slots = await ScheduleService(session, settings, tenant_id, branch_obj).available_slots(
            barber_id=barber_id, day=day, duration_minutes=30
        )
        assert slots
        assert all(9 <= slot.hour < 17 for slot in slots)


async def test_readiness_requires_schedule_even_with_bookable_barber(session_factory, onboarding_tenant):
    tenant_id = onboarding_tenant
    async with session_factory() as session:
        branch = await BranchRepository(session, tenant_id).create(name="Main")
        barber = await BarberRepository(session, tenant_id).create(name="Ion")
        await BranchRepository(session, tenant_id).assign_barber(
            barber_id=barber.id, branch_id=branch.id
        )
        await ServiceRepository(session, tenant_id).create(
            name="Cut", duration_minutes=30, price=Decimal("50")
        )
        await session.commit()

    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, tenant_id).validate_ready()
        assert readiness.is_ready is False
        assert readiness.missing == ["onboarding.missing_schedule"]


# --- H. Возобновляемость ---------------------------------------------------
async def test_readiness_shrinks_as_each_step_completes(session_factory, onboarding_tenant):
    """Имитирует остановку/перезапуск бота после каждого шага мастера —
    validate_ready каждый раз пересчитывается из данных, без сохранённого шага."""
    tenant_id = onboarding_tenant

    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, tenant_id).validate_ready()
    assert set(readiness.missing) == {
        "onboarding.missing_branch",
        "onboarding.missing_service",
        "onboarding.missing_barber",
    }

    async with session_factory() as session:
        branch = await BranchRepository(session, tenant_id).create(name="Main")
        await session.commit()
        branch_id = branch.id
    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, tenant_id).validate_ready()
    assert "onboarding.missing_branch" not in readiness.missing

    async with session_factory() as session:
        await ServiceRepository(session, tenant_id).create(
            name="Cut", duration_minutes=30, price=Decimal("50")
        )
        await session.commit()
    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, tenant_id).validate_ready()
    assert "onboarding.missing_service" not in readiness.missing
    assert "onboarding.missing_barber" in readiness.missing

    async with session_factory() as session:
        barber = await BarberRepository(session, tenant_id).create(name="Ion")
        await BranchRepository(session, tenant_id).assign_barber(
            barber_id=barber.id, branch_id=branch_id
        )
        await session.commit()
        barber_id = barber.id
    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, tenant_id).validate_ready()
    assert readiness.missing == ["onboarding.missing_schedule"]

    async with session_factory() as session:
        schedule_repo = ScheduleRepository(session, tenant_id)
        for weekday in range(7):
            await schedule_repo.set_day(barber_id, branch_id, weekday, time(10, 0), time(19, 0))
        await session.commit()
    async with session_factory() as session:
        readiness = await TenantOnboardingService(session, tenant_id).validate_ready()
    assert readiness.is_ready is True


# --- I. Идемпотентность ------------------------------------------------------
async def test_create_tenant_called_twice_makes_two_independent_tenants(session_factory):
    """create_tenant — примитив создания (не upsert): вызов дважды с разными
    slug создаёт два реальных, полностью изолированных арендатора."""
    async with session_factory() as session:
        first = await TenantOnboardingService.create_tenant(
            session, name="Dup", slug=f"dup1-{uuid.uuid4().hex[:8]}"
        )
        second = await TenantOnboardingService.create_tenant(
            session, name="Dup", slug=f"dup2-{uuid.uuid4().hex[:8]}"
        )
        first_id, second_id = first.id, second.id

    try:
        assert first_id != second_id
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_((first_id, second_id))))
            await session.commit()


# --- J. Безопасность --------------------------------------------------------
async def test_tenant_a_staff_cannot_activate_tenant_b(session_factory):
    async with session_factory() as session:
        tenant_a = await TenantOnboardingService.create_tenant(
            session, name="A", slug=f"a-{uuid.uuid4().hex[:8]}"
        )
        tenant_b = await TenantOnboardingService.create_tenant(
            session, name="B", slug=f"b-{uuid.uuid4().hex[:8]}"
        )
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id

    try:
        await _fully_configure(session_factory, tenant_a_id)
        # Полностью настраиваем ТОЛЬКО tenant_a. Активируем через сервис,
        # явно сконструированный для tenant_b — данные tenant_a физически
        # недостижимы через tenant-scoped репозитории с чужим tenant_id.
        async with session_factory() as session:
            readiness = await TenantOnboardingService(session, tenant_b_id).activate(
                actor_telegram_id=ADMIN_TELEGRAM_ID
            )
            assert readiness.is_ready is False

        async with session_factory() as session:
            tenant_b_reloaded = await TenantRepository(session).get(tenant_b_id)
            assert tenant_b_reloaded.status == TenantStatus.ONBOARDING
            tenant_a_reloaded = await TenantRepository(session).get(tenant_a_id)
            assert tenant_a_reloaded.status == TenantStatus.ONBOARDING  # ещё не активировали явно
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id))))
            await session.commit()


async def test_forged_branch_id_from_another_tenant_is_rejected_on_booking(
    session_factory, settings, onboarding_tenant
):
    tenant_id = onboarding_tenant
    async with session_factory() as session:
        other = await TenantOnboardingService.create_tenant(
            session, name="Other", slug=f"o-{uuid.uuid4().hex[:8]}"
        )
        other_id = other.id

    try:
        async with session_factory() as session:
            foreign_branch = await BranchRepository(session, other_id).create(name="Foreign")
            barber = await BarberRepository(session, tenant_id).create(name="Ion")
            service = await ServiceRepository(session, tenant_id).create(
                name="Cut", duration_minutes=30, price=Decimal("50")
            )
            user = User(tenant_id=tenant_id, telegram_id=800_600, full_name="Client")
            session.add(user)
            await session.commit()
            foreign_branch_id, barber_id, service_id, user_id = (
                foreign_branch.id,
                barber.id,
                service.id,
                user.id,
            )

        async with session_factory() as session:
            user_obj = await session.get(User, user_id)
            with pytest.raises(BookingError) as error:
                await BookingService(session, settings, tenant_id).create_appointment(
                    user=user_obj,
                    branch_id=foreign_branch_id,
                    barber_id=barber_id,
                    service_id=service_id,
                    start=target_slot(settings),
                )
            assert error.value.key == "error.branch_unavailable"
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == other_id))
            await session.commit()


# --- K. Регрессия существующего поведения ------------------------------------
async def test_existing_active_tenant_booking_flow_is_unaffected(session_factory, settings):
    """Арендатор, уже ACTIVE (как любой, что существовал до Phase 5, после
    бэкфилла миграции 0009), продолжает бронировать/отменять как раньше —
    ничего в BookingService не завязано на TenantStatus."""
    async with session_factory() as session:
        tenant = Tenant(
            name="Existing Shop", slug=f"existing-{uuid.uuid4().hex[:8]}", status=TenantStatus.ACTIVE
        )
        session.add(tenant)
        await session.flush()
        branch = Branch(tenant_id=tenant.id, name="Main")
        barber = Barber(tenant_id=tenant.id, name="Ion")
        service = Service(
            tenant_id=tenant.id, name="Cut", duration_minutes=60, price=Decimal("100")
        )
        user = User(tenant_id=tenant.id, telegram_id=800_700, full_name="Client")
        session.add_all([branch, barber, service, user])
        await session.flush()
        session.add(BarberBranch(tenant_id=tenant.id, barber_id=barber.id, branch_id=branch.id))
        for weekday in range(7):
            session.add(
                WorkingSchedule(
                    tenant_id=tenant.id,
                    barber_id=barber.id,
                    branch_id=branch.id,
                    weekday=weekday,
                    start_time=time(10, 0),
                    end_time=time(19, 0),
                )
            )
        await session.commit()
        tenant_id, branch_id, barber_id, service_id, user_id = (
            tenant.id,
            branch.id,
            barber.id,
            service.id,
            user.id,
        )

    try:
        async with session_factory() as session:
            user_obj = await session.get(User, user_id)
            appointment = await BookingService(session, settings, tenant_id).create_appointment(
                user=user_obj,
                branch_id=branch_id,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings),
            )
            assert appointment.status == AppointmentStatus.CONFIRMED

        async with session_factory() as session:
            cancelled = await BookingService(session, settings, tenant_id).cancel_appointment(
                appointment_id=appointment.id,
                cancelled_by=CancelledBy.CLIENT,
                actor_user_id=user_id,
            )
            assert cancelled.status == AppointmentStatus.CANCELLED
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()


# --- Вспомогательное ----------------------------------------------------------
async def _fully_configure(session_factory, tenant_id: uuid.UUID) -> None:
    """Доводит арендатора до состояния READY_TO_ACTIVATE напрямую через
    репозитории — то же самое, что делает мастер онбординга шаг за шагом."""
    async with session_factory() as session:
        branch = await BranchRepository(session, tenant_id).create(name="Main")
        barber = await BarberRepository(session, tenant_id).create(name="Ion")
        await BranchRepository(session, tenant_id).assign_barber(
            barber_id=barber.id, branch_id=branch.id
        )
        await ServiceRepository(session, tenant_id).create(
            name="Cut", duration_minutes=30, price=Decimal("50"), currency=branch.currency
        )
        schedule_repo = ScheduleRepository(session, tenant_id)
        for weekday in range(7):
            await schedule_repo.set_day(barber.id, branch.id, weekday, time(10, 0), time(19, 0))
        await session.commit()
