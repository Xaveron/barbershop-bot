"""Интеграционные тесты филиалов (Phase 3) на реальном PostgreSQL.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.config import Settings
from app.database import build_engine, build_session_factory
from app.database.models import (
    Appointment,
    Barber,
    BarberBranch,
    Branch,
    BranchService,
    Service,
    Tenant,
    User,
    WorkingSchedule,
)
from app.database.repositories import BranchRepository
from app.services.booking import BookingError, BookingService, SlotUnavailableError
from app.services.schedule import ScheduleService
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


# --- Изоляция и IDOR ---------------------------------------------------------
async def test_branches_are_isolated_between_tenants(session_factory):
    async with session_factory() as session:
        tenant_a = Tenant(name="Tenant A", slug=f"a-{uuid.uuid4().hex[:8]}")
        tenant_b = Tenant(name="Tenant B", slug=f"b-{uuid.uuid4().hex[:8]}")
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        branch_a = Branch(tenant_id=tenant_a.id, name="Branch A")
        session.add(branch_a)
        await session.commit()
        tenant_a_id, tenant_b_id, branch_a_id = tenant_a.id, tenant_b.id, branch_a.id

    try:
        async with session_factory() as session:
            # IDOR: чужой tenant_id не должен видеть филиал даже по точному UUID.
            assert await BranchRepository(session, tenant_b_id).get(branch_a_id) is None
            found = await BranchRepository(session, tenant_a_id).get(branch_a_id)
            assert found is not None and found.id == branch_a_id
    finally:
        async with session_factory() as session:
            await session.execute(delete(Branch).where(Branch.id == branch_a_id))
            await session.execute(delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id))))
            await session.commit()


async def test_assign_barber_rejects_barber_from_another_tenant(session_factory, tenant_id):
    async with session_factory() as session:
        other_tenant = Tenant(name="Other Tenant", slug=f"o-{uuid.uuid4().hex[:8]}")
        session.add(other_tenant)
        await session.flush()
        branch = Branch(tenant_id=tenant_id, name="Own Branch")
        foreign_barber = Barber(tenant_id=other_tenant.id, name="Foreign Barber")
        session.add_all([branch, foreign_barber])
        await session.commit()
        branch_id, other_tenant_id, foreign_barber_id = (
            branch.id,
            other_tenant.id,
            foreign_barber.id,
        )

    try:
        async with session_factory() as session:
            link = await BranchRepository(session, tenant_id).assign_barber(
                barber_id=foreign_barber_id, branch_id=branch_id
            )
            assert link is None

        async with session_factory() as session:
            leaked = await session.scalar(
                select(BarberBranch).where(BarberBranch.branch_id == branch_id)
            )
            assert leaked is None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Barber).where(Barber.id == foreign_barber_id))
            await session.execute(delete(Branch).where(Branch.id == branch_id))
            await session.execute(delete(Tenant).where(Tenant.id == other_tenant_id))
            await session.commit()


async def test_assign_barber_rejects_branch_from_another_tenant(session_factory, tenant_id):
    async with session_factory() as session:
        other_tenant = Tenant(name="Other Tenant", slug=f"o-{uuid.uuid4().hex[:8]}")
        session.add(other_tenant)
        await session.flush()
        barber = Barber(tenant_id=tenant_id, name="Own Barber")
        foreign_branch = Branch(tenant_id=other_tenant.id, name="Foreign Branch")
        session.add_all([barber, foreign_branch])
        await session.commit()
        barber_id, other_tenant_id, foreign_branch_id = (
            barber.id,
            other_tenant.id,
            foreign_branch.id,
        )

    try:
        async with session_factory() as session:
            link = await BranchRepository(session, tenant_id).assign_barber(
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
            await session.execute(delete(Barber).where(Barber.id == barber_id))
            await session.execute(delete(Branch).where(Branch.id == foreign_branch_id))
            await session.execute(delete(Tenant).where(Tenant.id == other_tenant_id))
            await session.commit()


async def test_assign_service_rejects_service_from_another_tenant(session_factory, tenant_id):
    """Тот же guard-паттерн, что assign_barber, но для branch_services."""
    async with session_factory() as session:
        other_tenant = Tenant(name="Other Tenant", slug=f"o-{uuid.uuid4().hex[:8]}")
        session.add(other_tenant)
        await session.flush()
        branch = Branch(tenant_id=tenant_id, name="Own Branch")
        foreign_service = Service(
            tenant_id=other_tenant.id, name="Foreign Cut", duration_minutes=30, price=Decimal("50")
        )
        session.add_all([branch, foreign_service])
        await session.commit()
        branch_id, other_tenant_id, foreign_service_id = (
            branch.id,
            other_tenant.id,
            foreign_service.id,
        )

    try:
        async with session_factory() as session:
            link = await BranchRepository(session, tenant_id).assign_service(
                service_id=foreign_service_id, branch_id=branch_id
            )
            assert link is None

        async with session_factory() as session:
            leaked = await session.scalar(
                select(BranchService).where(BranchService.branch_id == branch_id)
            )
            assert leaked is None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Service).where(Service.id == foreign_service_id))
            await session.execute(delete(Branch).where(Branch.id == branch_id))
            await session.execute(delete(Tenant).where(Tenant.id == other_tenant_id))
            await session.commit()


# --- Бронирование и филиалы --------------------------------------------------
@pytest.fixture
async def two_branch_shop(session_factory, tenant_id):
    """Один барбер, работающий в двух филиалах одного арендатора, с разными
    часами в каждом (одна услуга общая для обоих филиалов, один клиент)."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        branch_a = Branch(tenant_id=tenant_id, name=f"Branch A {marker}")
        branch_b = Branch(tenant_id=tenant_id, name=f"Branch B {marker}")
        barber = Barber(tenant_id=tenant_id, name=f"Barber {marker}")
        service = Service(
            tenant_id=tenant_id,
            name=f"Cut {marker}",
            duration_minutes=60,
            price=Decimal("250.00"),
        )
        user = User(
            tenant_id=tenant_id,
            telegram_id=950_000_000 + int(marker, 16) % 1_000_000,
            full_name="Test Client",
        )
        session.add_all([branch_a, branch_b, barber, service, user])
        await session.flush()
        session.add_all(
            [
                BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch_a.id),
                BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch_b.id),
            ]
        )
        for weekday in range(7):
            session.add(
                WorkingSchedule(
                    tenant_id=tenant_id,
                    barber_id=barber.id,
                    branch_id=branch_a.id,
                    weekday=weekday,
                    start_time=time(9, 0),
                    end_time=time(13, 0),
                )
            )
            session.add(
                WorkingSchedule(
                    tenant_id=tenant_id,
                    barber_id=barber.id,
                    branch_id=branch_b.id,
                    weekday=weekday,
                    start_time=time(14, 0),
                    end_time=time(18, 0),
                )
            )
        await session.commit()
        ids = (barber.id, service.id, user.id, branch_a.id, branch_b.id)

    yield ids

    async with session_factory() as session:
        await session.execute(delete(Appointment).where(Appointment.barber_id == ids[0]))
        await session.execute(delete(WorkingSchedule).where(WorkingSchedule.barber_id == ids[0]))
        await session.execute(delete(BarberBranch).where(BarberBranch.barber_id == ids[0]))
        await session.execute(delete(Barber).where(Barber.id == ids[0]))
        await session.execute(delete(Service).where(Service.id == ids[1]))
        await session.execute(delete(User).where(User.id == ids[2]))
        await session.execute(delete(Branch).where(Branch.id.in_((ids[3], ids[4]))))
        await session.commit()


async def test_create_appointment_rejects_barber_not_at_branch(
    session_factory, settings, tenant_id
):
    """Барбер не привязан к филиалу — попытка записи туда отклоняется, строка не создаётся."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        branch = Branch(tenant_id=tenant_id, name=f"Lonely Branch {marker}")
        barber = Barber(tenant_id=tenant_id, name=f"Unassigned Barber {marker}")
        service = Service(
            tenant_id=tenant_id, name=f"Cut {marker}", duration_minutes=60, price=Decimal("100")
        )
        user = User(
            tenant_id=tenant_id, telegram_id=960_000_000 + int(marker, 16) % 1_000_000,
            full_name="Client",
        )
        session.add_all([branch, barber, service, user])
        await session.commit()
        branch_id, barber_id, service_id, user_id = branch.id, barber.id, service.id, user.id

    try:
        async with session_factory() as session:
            user_obj = await _load_user(session, user_id)
            with pytest.raises(BookingError) as error:
                await BookingService(session, settings, tenant_id).create_appointment(
                    user=user_obj,
                    branch_id=branch_id,
                    barber_id=barber_id,
                    service_id=service_id,
                    start=target_slot(settings),
                )
            assert error.value.key == "error.barber_not_at_branch"

        async with session_factory() as session:
            leaked = await session.scalar(
                select(Appointment).where(Appointment.barber_id == barber_id)
            )
            assert leaked is None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Barber).where(Barber.id == barber_id))
            await session.execute(delete(Service).where(Service.id == service_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.execute(delete(Branch).where(Branch.id == branch_id))
            await session.commit()


@pytest.fixture
async def overlapping_hours_shop(session_factory, tenant_id):
    """Тот же барбер в двух филиалах, но с ОДИНАКОВЫМИ (пересекающимися)
    рабочими часами в обоих — изолирует проверку «один и тот же барбер не
    может быть занят одновременно в двух местах» от фильтрации по часам."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        branch_a = Branch(tenant_id=tenant_id, name=f"Branch A {marker}")
        branch_b = Branch(tenant_id=tenant_id, name=f"Branch B {marker}")
        barber = Barber(tenant_id=tenant_id, name=f"Barber {marker}")
        service = Service(
            tenant_id=tenant_id, name=f"Cut {marker}", duration_minutes=60, price=Decimal("250")
        )
        user = User(
            tenant_id=tenant_id,
            telegram_id=970_000_000 + int(marker, 16) % 1_000_000,
            full_name="Test Client",
        )
        session.add_all([branch_a, branch_b, barber, service, user])
        await session.flush()
        session.add_all(
            [
                BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch_a.id),
                BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch_b.id),
            ]
        )
        for branch in (branch_a, branch_b):
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
        await session.commit()
        ids = (barber.id, service.id, user.id, branch_a.id, branch_b.id)

    yield ids

    async with session_factory() as session:
        await session.execute(delete(Appointment).where(Appointment.barber_id == ids[0]))
        await session.execute(delete(WorkingSchedule).where(WorkingSchedule.barber_id == ids[0]))
        await session.execute(delete(BarberBranch).where(BarberBranch.barber_id == ids[0]))
        await session.execute(delete(Barber).where(Barber.id == ids[0]))
        await session.execute(delete(Service).where(Service.id == ids[1]))
        await session.execute(delete(User).where(User.id == ids[2]))
        await session.execute(delete(Branch).where(Branch.id.in_((ids[3], ids[4]))))
        await session.commit()


async def test_double_booking_is_rejected_across_branches(
    session_factory, settings, tenant_id, overlapping_hours_shop
):
    """Регрессия ключевого инварианта Phase 3: EXCLUDE-констрейнт и is_slot_available
    держат занятость барбера по нему самому, а не по (barber, branch) — иначе
    один и тот же человек мог бы оказаться забронирован в двух филиалах разом."""
    barber_id, service_id, user_id, branch_a_id, branch_b_id = overlapping_hours_shop
    start = target_slot(settings, hour=11)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        await BookingService(session, settings, tenant_id).create_appointment(
            user=user,
            branch_id=branch_a_id,
            barber_id=barber_id,
            service_id=service_id,
            start=start,
        )

    # Тот же барбер, то же время, другой филиал (с точно такими же рабочими
    # часами) — is_slot_available видит его занятым (busy не фильтруется по
    # branch_id), запись отклоняется именно как конфликт занятости.
    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(SlotUnavailableError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                branch_id=branch_b_id,
                barber_id=barber_id,
                service_id=service_id,
                start=start,
            )

    async with session_factory() as session:
        all_ids = list(
            await session.scalars(
                select(Appointment.id).where(Appointment.barber_id == barber_id)
            )
        )
        assert len(all_ids) == 1


async def test_available_slots_differ_per_branch_for_same_barber(
    session_factory, settings, tenant_id, two_branch_shop
):
    """Один барбер, разные часы в разных филиалах: available_slots должен
    возвращать окно филиала A при branch_id=A и окно филиала Б при branch_id=Б,
    без утечки часов одного филиала в другой."""
    barber_id, _service_id, _user_id, branch_a_id, branch_b_id = two_branch_shop
    day = (now_utc().astimezone(settings.tz) + timedelta(days=2)).date()

    async with session_factory() as session:
        branch_repo = BranchRepository(session, tenant_id)
        branch_a = await branch_repo.get(branch_a_id)
        branch_b = await branch_repo.get(branch_b_id)
        slots_a = await ScheduleService(session, settings, tenant_id, branch_a).available_slots(
            barber_id=barber_id, day=day, duration_minutes=60
        )
        slots_b = await ScheduleService(session, settings, tenant_id, branch_b).available_slots(
            barber_id=barber_id, day=day, duration_minutes=60
        )

    assert slots_a, "у филиала A должны быть слоты в окне 9:00-13:00"
    assert slots_b, "у филиала B должны быть слоты в окне 14:00-18:00"
    assert all(9 <= slot.hour < 13 for slot in slots_a)
    assert all(14 <= slot.hour < 18 for slot in slots_b)
    assert set(slots_a).isdisjoint(slots_b)
