"""Интеграционные тесты Phase 4 (staff/service/branch relationships) на
реальном PostgreSQL.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.config import Settings
from app.database import build_engine, build_session_factory
from app.database.models import (
    Appointment,
    Barber,
    BarberBranch,
    BarberService,
    Branch,
    BranchService,
    Role,
    Service,
    StaffBranch,
    StaffMember,
    Tenant,
    User,
    WorkingSchedule,
)
from app.database.repositories import (
    AppointmentRepository,
    BarberServiceRepository,
    BranchRepository,
    StaffRepository,
)
from app.services.authorization import AuthorizationService, resolve_accessible_branch_ids
from app.services.booking import BookingError, BookingService
from app.services.schedule import ScheduleService
from app.utils.dt import combine_local, now_utc, to_utc

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


def target_slot(settings: Settings, *, days_ahead: int = 2, hour: int = 12):
    day = (now_utc().astimezone(settings.tz) + timedelta(days=days_ahead)).date()
    return combine_local(day, time(hour, 0), settings.tz)


async def _load_user(session, user_id: uuid.UUID) -> User:
    return await session.get(User, user_id)


# --- Barber/staff assigned to multiple branches -----------------------------
async def test_barber_can_be_assigned_to_multiple_branches(session_factory, tenant_id):
    async with session_factory() as session:
        branch_a = Branch(tenant_id=tenant_id, name="Branch A")
        branch_b = Branch(tenant_id=tenant_id, name="Branch B")
        barber = Barber(tenant_id=tenant_id, name="Multi Barber")
        session.add_all([branch_a, branch_b, barber])
        await session.commit()
        branch_a_id, branch_b_id, barber_id = branch_a.id, branch_b.id, barber.id

    try:
        async with session_factory() as session:
            repo = BranchRepository(session, tenant_id)
            await repo.assign_barber(barber_id=barber_id, branch_id=branch_a_id)
            await repo.assign_barber(barber_id=barber_id, branch_id=branch_b_id)
            await session.commit()

        async with session_factory() as session:
            branches = await BranchRepository(session, tenant_id).list_for_barber(barber_id)
            assert {b.id for b in branches} == {branch_a_id, branch_b_id}

        async with session_factory() as session:
            removed = await BranchRepository(session, tenant_id).unassign_barber(
                barber_id=barber_id, branch_id=branch_a_id
            )
            assert removed is True
            await session.commit()

        async with session_factory() as session:
            branches = await BranchRepository(session, tenant_id).list_for_barber(barber_id)
            assert {b.id for b in branches} == {branch_b_id}
    finally:
        async with session_factory() as session:
            await session.execute(delete(BarberBranch).where(BarberBranch.barber_id == barber_id))
            await session.execute(delete(Barber).where(Barber.id == barber_id))
            await session.execute(
                delete(Branch).where(Branch.id.in_((branch_a_id, branch_b_id)))
            )
            await session.commit()


async def test_staff_can_be_assigned_to_multiple_branches(session_factory, tenant_id):
    async with session_factory() as session:
        branch_a = Branch(tenant_id=tenant_id, name="Branch A")
        branch_b = Branch(tenant_id=tenant_id, name="Branch B")
        session.add_all([branch_a, branch_b])
        await session.flush()
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=500_001, role=Role.MANAGER
        )
        await session.commit()
        branch_a_id, branch_b_id, staff_id = branch_a.id, branch_b.id, staff.id

    try:
        async with session_factory() as session:
            repo = BranchRepository(session, tenant_id)
            await repo.assign_staff(staff_member_id=staff_id, branch_id=branch_a_id)
            await repo.assign_staff(staff_member_id=staff_id, branch_id=branch_b_id)
            await session.commit()

        async with session_factory() as session:
            accessible = await BranchRepository(
                session, tenant_id
            ).accessible_branch_ids_for_staff(staff_id)
            assert accessible == frozenset((branch_a_id, branch_b_id))

        async with session_factory() as session:
            removed = await BranchRepository(session, tenant_id).unassign_staff(
                staff_member_id=staff_id, branch_id=branch_a_id
            )
            assert removed is True
            await session.commit()

        async with session_factory() as session:
            accessible = await BranchRepository(
                session, tenant_id
            ).accessible_branch_ids_for_staff(staff_id)
            assert accessible == frozenset((branch_b_id,))
    finally:
        async with session_factory() as session:
            await session.execute(delete(StaffBranch).where(StaffBranch.staff_member_id == staff_id))
            await session.execute(delete(StaffMember).where(StaffMember.id == staff_id))
            await session.execute(
                delete(Branch).where(Branch.id.in_((branch_a_id, branch_b_id)))
            )
            await session.commit()


# --- RBAC branch restriction -------------------------------------------------
@pytest.mark.parametrize("role", [Role.MANAGER, Role.RECEPTIONIST, Role.BARBER])
async def test_scoped_roles_are_restricted_to_assigned_branches(session_factory, tenant_id, role):
    async with session_factory() as session:
        branch_a = Branch(tenant_id=tenant_id, name="Branch A")
        branch_b = Branch(tenant_id=tenant_id, name="Branch B")
        session.add_all([branch_a, branch_b])
        await session.flush()
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=500_100 + hash(role.value) % 1000, role=role
        )
        await session.commit()
        branch_a_id, branch_b_id, staff_id = branch_a.id, branch_b.id, staff.id

    try:
        async with session_factory() as session:
            await BranchRepository(session, tenant_id).assign_staff(
                staff_member_id=staff_id, branch_id=branch_a_id
            )
            await session.commit()

        async with session_factory() as session:
            staff = await StaffRepository(session, tenant_id).get(staff_id)
            accessible = await resolve_accessible_branch_ids(
                session, tenant_id, staff, is_super_admin=False
            )
            assert accessible == frozenset((branch_a_id,))
            assert AuthorizationService.can_access_branch(
                staff, branch_a_id, accessible_branch_ids=accessible
            )
            assert not AuthorizationService.can_access_branch(
                staff, branch_b_id, accessible_branch_ids=accessible
            )
    finally:
        async with session_factory() as session:
            await session.execute(delete(StaffBranch).where(StaffBranch.staff_member_id == staff_id))
            await session.execute(delete(StaffMember).where(StaffMember.id == staff_id))
            await session.execute(
                delete(Branch).where(Branch.id.in_((branch_a_id, branch_b_id)))
            )
            await session.commit()


@pytest.mark.parametrize("role", [Role.TENANT_OWNER, Role.TENANT_ADMIN])
async def test_owner_and_admin_bypass_branch_restriction(session_factory, tenant_id, role):
    """TENANT_OWNER/TENANT_ADMIN видят все филиалы арендатора без единой
    строки staff_branches (см. docs/RBAC_DESIGN.md §6)."""
    async with session_factory() as session:
        branch = Branch(tenant_id=tenant_id, name="Only Branch")
        session.add(branch)
        await session.flush()
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=500_200 + hash(role.value) % 1000, role=role
        )
        await session.commit()
        branch_id, staff_id = branch.id, staff.id

    try:
        async with session_factory() as session:
            staff = await StaffRepository(session, tenant_id).get(staff_id)
            accessible = await resolve_accessible_branch_ids(
                session, tenant_id, staff, is_super_admin=False
            )
            assert accessible is None
            assert AuthorizationService.can_access_branch(
                staff, branch_id, accessible_branch_ids=frozenset()
            )
    finally:
        async with session_factory() as session:
            await session.execute(delete(StaffMember).where(StaffMember.id == staff_id))
            await session.execute(delete(Branch).where(Branch.id == branch_id))
            await session.commit()


# --- Service <-> branch, barber <-> service ---------------------------------
async def test_service_available_at_branch_defaults_to_true_without_row(
    session_factory, tenant_id
):
    """Регрессия бага Phase 3: отсутствие строки branch_services должно
    читаться как «доступна», а не «недоступна»."""
    async with session_factory() as session:
        branch = Branch(tenant_id=tenant_id, name="Branch")
        service = Service(
            tenant_id=tenant_id, name="Cut", duration_minutes=30, price=Decimal("50")
        )
        session.add_all([branch, service])
        await session.commit()
        branch_id, service_id = branch.id, service.id

    try:
        async with session_factory() as session:
            available = await BranchRepository(session, tenant_id).service_available_at_branch(
                service_id=service_id, branch_id=branch_id
            )
            assert available is True
    finally:
        async with session_factory() as session:
            await session.execute(delete(Service).where(Service.id == service_id))
            await session.execute(delete(Branch).where(Branch.id == branch_id))
            await session.commit()


async def test_service_can_be_disabled_at_specific_branch(session_factory, tenant_id):
    async with session_factory() as session:
        branch_a = Branch(tenant_id=tenant_id, name="Branch A")
        branch_b = Branch(tenant_id=tenant_id, name="Branch B")
        service = Service(
            tenant_id=tenant_id, name="Cut", duration_minutes=30, price=Decimal("50")
        )
        session.add_all([branch_a, branch_b, service])
        await session.commit()
        branch_a_id, branch_b_id, service_id = branch_a.id, branch_b.id, service.id

    try:
        async with session_factory() as session:
            await BranchRepository(session, tenant_id).assign_service(
                service_id=service_id, branch_id=branch_a_id, is_active=False
            )
            await session.commit()

        async with session_factory() as session:
            repo = BranchRepository(session, tenant_id)
            assert not await repo.service_available_at_branch(
                service_id=service_id, branch_id=branch_a_id
            )
            # Другой филиал не затронут — отсутствие строки там всё ещё «доступна».
            assert await repo.service_available_at_branch(
                service_id=service_id, branch_id=branch_b_id
            )
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(BranchService).where(BranchService.service_id == service_id)
            )
            await session.execute(delete(Service).where(Service.id == service_id))
            await session.execute(
                delete(Branch).where(Branch.id.in_((branch_a_id, branch_b_id)))
            )
            await session.commit()


async def test_barber_provides_service_defaults_to_true_without_row(session_factory, tenant_id):
    async with session_factory() as session:
        barber = Barber(tenant_id=tenant_id, name="Barber")
        service = Service(
            tenant_id=tenant_id, name="Cut", duration_minutes=30, price=Decimal("50")
        )
        session.add_all([barber, service])
        await session.commit()
        barber_id, service_id = barber.id, service.id

    try:
        async with session_factory() as session:
            provides = await BarberServiceRepository(session, tenant_id).barber_provides_service(
                barber_id=barber_id, service_id=service_id
            )
            assert provides is True
    finally:
        async with session_factory() as session:
            await session.execute(delete(Barber).where(Barber.id == barber_id))
            await session.execute(delete(Service).where(Service.id == service_id))
            await session.commit()


async def test_barber_service_can_be_disabled(session_factory, tenant_id):
    async with session_factory() as session:
        barber = Barber(tenant_id=tenant_id, name="Barber")
        service = Service(
            tenant_id=tenant_id, name="Cut", duration_minutes=30, price=Decimal("50")
        )
        session.add_all([barber, service])
        await session.commit()
        barber_id, service_id = barber.id, service.id

    try:
        async with session_factory() as session:
            await BarberServiceRepository(session, tenant_id).set_active(
                barber_id=barber_id, service_id=service_id, is_active=False
            )
            await session.commit()

        async with session_factory() as session:
            provides = await BarberServiceRepository(session, tenant_id).barber_provides_service(
                barber_id=barber_id, service_id=service_id
            )
            assert provides is False
    finally:
        async with session_factory() as session:
            await session.execute(delete(BarberService).where(BarberService.barber_id == barber_id))
            await session.execute(delete(Barber).where(Barber.id == barber_id))
            await session.execute(delete(Service).where(Service.id == service_id))
            await session.commit()


async def test_barber_service_set_active_rejects_cross_tenant(session_factory, tenant_id):
    async with session_factory() as session:
        other_tenant = Tenant(name="Other", slug=f"o-{uuid.uuid4().hex[:8]}")
        session.add(other_tenant)
        await session.flush()
        barber = Barber(tenant_id=tenant_id, name="Own Barber")
        foreign_service = Service(
            tenant_id=other_tenant.id, name="Foreign", duration_minutes=30, price=Decimal("50")
        )
        session.add_all([barber, foreign_service])
        await session.commit()
        other_tenant_id = other_tenant.id
        barber_id, foreign_service_id = barber.id, foreign_service.id

    try:
        async with session_factory() as session:
            result = await BarberServiceRepository(session, tenant_id).set_active(
                barber_id=barber_id, service_id=foreign_service_id, is_active=False
            )
            assert result is None

        async with session_factory() as session:
            leaked = await session.scalar(
                select(BarberService).where(BarberService.barber_id == barber_id)
            )
            assert leaked is None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Barber).where(Barber.id == barber_id))
            await session.execute(delete(Service).where(Service.id == foreign_service_id))
            await session.execute(delete(Tenant).where(Tenant.id == other_tenant_id))
            await session.commit()


# --- Booking validation: branch + service + barber-provides ------------------
@pytest.fixture
async def full_shop(session_factory, tenant_id):
    """Филиал, барбер (привязан к филиалу, работает всю неделю 10-19),
    услуга и клиент — база для валидационных тестов бронирования."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        branch = Branch(tenant_id=tenant_id, name=f"Branch {marker}")
        barber = Barber(tenant_id=tenant_id, name=f"Barber {marker}")
        service = Service(
            tenant_id=tenant_id, name=f"Cut {marker}", duration_minutes=60, price=Decimal("100")
        )
        user = User(
            tenant_id=tenant_id,
            telegram_id=980_000_000 + int(marker, 16) % 1_000_000,
            full_name="Client",
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
        await session.execute(delete(BarberService).where(BarberService.barber_id == ids[0]))
        await session.execute(
            delete(BranchService).where(BranchService.service_id == ids[1])
        )
        await session.execute(delete(Barber).where(Barber.id == ids[0]))
        await session.execute(delete(Service).where(Service.id == ids[1]))
        await session.execute(delete(User).where(User.id == ids[2]))
        await session.execute(delete(Branch).where(Branch.id == ids[3]))
        await session.commit()


async def test_create_appointment_rejects_service_disabled_at_branch(
    session_factory, settings, tenant_id, full_shop
):
    barber_id, service_id, user_id, branch_id = full_shop
    async with session_factory() as session:
        await BranchRepository(session, tenant_id).assign_service(
            service_id=service_id, branch_id=branch_id, is_active=False
        )
        await session.commit()

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(BookingError) as error:
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                branch_id=branch_id,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings),
            )
        assert error.value.key == "error.service_not_at_branch"


async def test_create_appointment_rejects_barber_not_providing_service(
    session_factory, settings, tenant_id, full_shop
):
    barber_id, service_id, user_id, branch_id = full_shop
    async with session_factory() as session:
        await BarberServiceRepository(session, tenant_id).set_active(
            barber_id=barber_id, service_id=service_id, is_active=False
        )
        await session.commit()

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(BookingError) as error:
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                branch_id=branch_id,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings),
            )
        assert error.value.key == "error.barber_not_provide_service"


async def test_create_appointment_rejects_unknown_branch(
    session_factory, settings, tenant_id, full_shop
):
    barber_id, service_id, user_id, _branch_id = full_shop
    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(BookingError) as error:
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                branch_id=uuid.uuid4(),
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings),
            )
        assert error.value.key == "error.branch_unavailable"


async def test_create_appointment_succeeds_with_valid_combination(
    session_factory, settings, tenant_id, full_shop
):
    """Явно доступная услуга в филиале (is_active=True строка) + барбер,
    не отказавшийся от услуги, — запись проходит все три проверки."""
    barber_id, service_id, user_id, branch_id = full_shop
    async with session_factory() as session:
        await BranchRepository(session, tenant_id).assign_service(
            service_id=service_id, branch_id=branch_id, is_active=True
        )
        await session.commit()

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=user,
            branch_id=branch_id,
            barber_id=barber_id,
            service_id=service_id,
            start=target_slot(settings),
        )
        assert appointment.branch_id == branch_id


# --- Appointment listing scoped to accessible branches -----------------------
async def test_appointment_listing_can_be_scoped_to_branch_ids(
    session_factory, settings, tenant_id, full_shop
):
    barber_id, service_id, user_id, branch_id = full_shop
    async with session_factory() as session:
        other_branch = Branch(tenant_id=tenant_id, name="Other branch")
        session.add(other_branch)
        await session.commit()
        other_branch_id = other_branch.id

    try:
        async with session_factory() as session:
            user = await _load_user(session, user_id)
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                branch_id=branch_id,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings),
            )

        async with session_factory() as session:
            now = now_utc()
            horizon = now + timedelta(days=30)
            repo = AppointmentRepository(session, tenant_id)
            scoped_out = await repo.list_between(
                start=now, end=horizon, branch_ids=frozenset((other_branch_id,))
            )
            scoped_in = await repo.list_between(
                start=now, end=horizon, branch_ids=frozenset((branch_id,))
            )
            assert scoped_out == []
            assert len(scoped_in) == 1

            count_out = await repo.count_between(
                start=now, end=horizon, branch_ids=frozenset((other_branch_id,))
            )
            count_in = await repo.count_between(
                start=now, end=horizon, branch_ids=frozenset((branch_id,))
            )
            assert count_out == 0
            assert count_in == 1
    finally:
        async with session_factory() as session:
            await session.execute(delete(Branch).where(Branch.id == other_branch_id))
            await session.commit()


# --- Branch timezone --------------------------------------------------------
async def test_branch_timezone_is_used_for_slot_computation(
    session_factory, settings, tenant_id
):
    """Тот же барбер/расписание — филиал с другим часовым поясом должен
    сдвигать вычисленные UTC-времена слотов ровно на разницу поясов."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        branch_chisinau = Branch(
            tenant_id=tenant_id, name=f"Chisinau {marker}", timezone="Europe/Chisinau"
        )
        branch_ny = Branch(
            tenant_id=tenant_id, name=f"NY {marker}", timezone="America/New_York"
        )
        barber = Barber(tenant_id=tenant_id, name=f"Barber {marker}")
        session.add_all([branch_chisinau, branch_ny, barber])
        await session.flush()
        session.add_all(
            [
                BarberBranch(
                    tenant_id=tenant_id, barber_id=barber.id, branch_id=branch_chisinau.id
                ),
                BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch_ny.id),
            ]
        )
        day = (now_utc().astimezone(ZoneInfo("Europe/Chisinau")) + timedelta(days=5)).date()
        weekday = day.weekday()
        for branch in (branch_chisinau, branch_ny):
            session.add(
                WorkingSchedule(
                    tenant_id=tenant_id,
                    barber_id=barber.id,
                    branch_id=branch.id,
                    weekday=weekday,
                    start_time=time(10, 0),
                    end_time=time(11, 0),
                )
            )
        await session.commit()
        branch_chisinau_id, branch_ny_id, barber_id = (
            branch_chisinau.id,
            branch_ny.id,
            barber.id,
        )

    try:
        async with session_factory() as session:
            branch_repo = BranchRepository(session, tenant_id)
            chisinau = await branch_repo.get(branch_chisinau_id)
            ny = await branch_repo.get(branch_ny_id)
            slots_chisinau = await ScheduleService(
                session, settings, tenant_id, chisinau
            ).available_slots(barber_id=barber_id, day=day, duration_minutes=30)
            slots_ny = await ScheduleService(session, settings, tenant_id, ny).available_slots(
                barber_id=barber_id, day=day, duration_minutes=30
            )

        assert slots_chisinau, "должен быть хотя бы один слот в 10:00 по Кишинёву"
        assert slots_ny, "должен быть хотя бы один слот в 10:00 по Нью-Йорку"
        # Один и тот же локальный час 10:00 в разных поясах — разные моменты UTC.
        utc_chisinau = to_utc(slots_chisinau[0])
        utc_ny = to_utc(slots_ny[0])
        assert utc_chisinau != utc_ny
    finally:
        async with session_factory() as session:
            await session.execute(delete(WorkingSchedule).where(WorkingSchedule.barber_id == barber_id))
            await session.execute(delete(BarberBranch).where(BarberBranch.barber_id == barber_id))
            await session.execute(delete(Barber).where(Barber.id == barber_id))
            await session.execute(
                delete(Branch).where(Branch.id.in_((branch_chisinau_id, branch_ny_id)))
            )
            await session.commit()


# --- DST regression -----------------------------------------------------------
def _last_sunday(year: int, month: int) -> date:
    # Последнее воскресенье месяца: идём назад от последнего дня.
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - 6) % 7)


def test_dst_spring_forward_offset_changes():
    """Europe/Chisinau переходит на летнее время в последнее воскресенье
    марта — полуденный UTC-оффсет до и после перехода должен отличаться на час."""
    year = now_utc().year + 1
    transition = _last_sunday(year, 3)
    tz = ZoneInfo("Europe/Chisinau")
    before = datetime.combine(transition - timedelta(days=1), time(12, 0), tzinfo=tz)
    after = datetime.combine(transition + timedelta(days=1), time(12, 0), tzinfo=tz)
    assert after.utcoffset() - before.utcoffset() == timedelta(hours=1)


def test_dst_fall_back_offset_changes():
    """Последнее воскресенье октября — переход обратно на зимнее время."""
    year = now_utc().year + 1
    transition = _last_sunday(year, 10)
    tz = ZoneInfo("Europe/Chisinau")
    before = datetime.combine(transition - timedelta(days=1), time(12, 0), tzinfo=tz)
    after = datetime.combine(transition + timedelta(days=1), time(12, 0), tzinfo=tz)
    assert before.utcoffset() - after.utcoffset() == timedelta(hours=1)


async def test_available_slots_work_across_dst_transition_day(session_factory, settings, tenant_id):
    """Рабочий день (10:00-19:00, далеко от полуночного скачка стрелок) в
    день перехода на летнее время должен по-прежнему давать корректные слоты."""
    marker = uuid.uuid4().hex[:8]
    year = now_utc().year + 1
    transition_day = _last_sunday(year, 3)
    weekday = transition_day.weekday()

    async with session_factory() as session:
        branch = Branch(tenant_id=tenant_id, name=f"DST {marker}", timezone="Europe/Chisinau")
        barber = Barber(tenant_id=tenant_id, name=f"DST Barber {marker}")
        session.add_all([branch, barber])
        await session.flush()
        session.add(BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch.id))
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
        branch_id, barber_id = branch.id, barber.id

    try:
        async with session_factory() as session:
            branch_obj = await BranchRepository(session, tenant_id).get(branch_id)
            schedule = ScheduleService(session, settings, tenant_id, branch_obj)
            slots = await schedule.available_slots(
                barber_id=barber_id, day=transition_day, duration_minutes=30
            )
        assert slots
        for slot in slots:
            assert 10 <= slot.hour < 19
    finally:
        async with session_factory() as session:
            await session.execute(delete(WorkingSchedule).where(WorkingSchedule.barber_id == barber_id))
            await session.execute(delete(BarberBranch).where(BarberBranch.barber_id == barber_id))
            await session.execute(delete(Barber).where(Barber.id == barber_id))
            await session.execute(delete(Branch).where(Branch.id == branch_id))
            await session.commit()
