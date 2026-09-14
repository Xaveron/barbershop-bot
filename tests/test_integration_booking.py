"""Интеграционные тесты бронирования на реальном PostgreSQL.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции:

    export TEST_DATABASE_URL=postgresql+asyncpg://barber:barber@localhost:5432/barbershop
    alembic upgrade head && pytest tests/test_integration_booking.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import time, timedelta
from decimal import Decimal
from time import perf_counter

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.database import build_engine, build_session_factory
from app.database.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    CancelledBy,
    Notification,
    NotificationStatus,
    ScheduleException,
    Service,
    Tenant,
    User,
    WorkingSchedule,
)
from app.database.repositories import AppointmentRepository, BarberRepository, ServiceRepository
from app.services.booking import (
    AppointmentNotFoundError,
    BookingError,
    BookingService,
    SlotUnavailableError,
    TooManyActiveAppointmentsError,
    _advisory_lock_key,
)
from app.services.notifications import NotificationService
from app.services.schedule import ScheduleService
from app.services.stats import StatsService
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
def query_counter(engine):
    """Считает SQL-запросы — регрессионная защита от N+1."""
    queries: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    yield queries
    event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)


@pytest.fixture
async def tenant_id(session_factory):
    """Отдельный арендатор на тест — не пересекается с другими тестами/данными."""
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
async def fixtures(session_factory, settings: Settings, tenant_id):
    """Барбер (работает всю неделю 10:00–19:00), услуга 60 минут и клиент."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
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
        session.add_all([barber, service, user])
        await session.flush()
        for weekday in range(7):
            session.add(
                WorkingSchedule(
                    tenant_id=tenant_id,
                    barber_id=barber.id,
                    weekday=weekday,
                    start_time=time(10, 0),
                    end_time=time(19, 0),
                )
            )
        await session.commit()
        ids = (barber.id, service.id, user.id)

    yield ids

    async with session_factory() as session:
        await session.execute(delete(Appointment).where(Appointment.barber_id == ids[0]))
        await session.execute(delete(WorkingSchedule).where(WorkingSchedule.barber_id == ids[0]))
        await session.execute(delete(Barber).where(Barber.id == ids[0]))
        await session.execute(delete(Service).where(Service.id == ids[1]))
        await session.execute(delete(User).where(User.id == ids[2]))
        await session.commit()


def target_slot(settings: Settings, *, days_ahead: int = 2, hour: int = 12):
    day = (now_utc().astimezone(settings.tz) + timedelta(days=days_ahead)).date()
    return combine_local(day, time(hour, 0), settings.tz)


async def _load_user(session, user_id: uuid.UUID) -> User:
    return await session.get(User, user_id)


async def test_create_appointment_and_plan_reminders(session_factory, settings, tenant_id, fixtures):
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=start
        )
        assert appointment.status == AppointmentStatus.CONFIRMED
        assert appointment.ends_at - appointment.starts_at == timedelta(minutes=60)

        notifications = list(
            await session.scalars(
                select(Notification).where(Notification.appointment_id == appointment.id)
            )
        )
        assert len(notifications) == 2
        assert all(item.status == NotificationStatus.PENDING for item in notifications)


async def test_double_booking_is_rejected_by_service(session_factory, settings, tenant_id, fixtures):
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        await BookingService(session, settings, tenant_id).create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=start
        )

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(SlotUnavailableError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                barber_id=barber_id,
                service_id=service_id,
                start=start + timedelta(minutes=30),
            )


async def test_overlap_is_rejected_by_database_constraint(
    session_factory, settings, tenant_id, fixtures
):
    """Даже прямой INSERT в обход сервиса не создаст пересечение."""
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        await BookingService(session, settings, tenant_id).create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=start
        )

    async with session_factory() as session:
        session.add(
            Appointment(
                tenant_id=tenant_id,
                user_id=user_id,
                barber_id=barber_id,
                service_id=service_id,
                starts_at=start + timedelta(minutes=15),
                ends_at=start + timedelta(minutes=75),
                status=AppointmentStatus.CONFIRMED,
                price=Decimal("250.00"),
                duration_minutes=60,
            )
        )
        with pytest.raises(IntegrityError) as error:
            await session.flush()
        assert "excl_appointments_barber_no_overlap" in str(error.value.orig)
        await session.rollback()


async def test_concurrent_booking_creates_only_one_appointment(
    session_factory, settings, tenant_id, fixtures
):
    """Гонка двух клиентов за один слот: побеждает ровно один."""
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, hour=14)

    async def attempt():
        async with session_factory() as session:
            user = await _load_user(session, user_id)
            try:
                await BookingService(session, settings, tenant_id).create_appointment(
                    user=user, barber_id=barber_id, service_id=service_id, start=start
                )
            except SlotUnavailableError:
                return False
            return True

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == [False, True]

    async with session_factory() as session:
        total = await session.scalar(
            select(text("count(*)")).select_from(Appointment).where(
                Appointment.barber_id == barber_id,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
        )
        assert total == 1


async def test_concurrent_booking_respects_active_appointment_limit(
    session_factory, settings, tenant_id, fixtures
):
    """Гонка одного клиента за разные слоты: проходит не больше max_active_appointments.

    Слоты и барбер общие, но не пересекаются — _lock_barber тут не сериализует
    попытки, поэтому лимит обязан держаться на отдельном локе по клиенту.
    """
    barber_id, service_id, user_id = fixtures
    hours = (10, 11, 12, 13, 14)
    assert len(hours) > settings.max_active_appointments

    async def attempt(hour: int) -> bool:
        async with session_factory() as session:
            user = await _load_user(session, user_id)
            try:
                await BookingService(session, settings, tenant_id).create_appointment(
                    user=user,
                    barber_id=barber_id,
                    service_id=service_id,
                    start=target_slot(settings, hour=hour),
                )
            except TooManyActiveAppointmentsError:
                return False
            return True

    results = await asyncio.gather(*(attempt(hour) for hour in hours))
    assert sum(results) == settings.max_active_appointments

    async with session_factory() as session:
        total = await session.scalar(
            select(text("count(*)")).select_from(Appointment).where(
                Appointment.user_id == user_id,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
        )
        assert total == settings.max_active_appointments


async def test_appointments_are_isolated_between_tenants(session_factory, settings):
    """Два арендатора, одинаковые по форме данные, ноль утечек через сервис и репозитории."""
    async with session_factory() as session:
        tenant_a = Tenant(name="Tenant A", slug=f"a-{uuid.uuid4().hex[:8]}")
        tenant_b = Tenant(name="Tenant B", slug=f"b-{uuid.uuid4().hex[:8]}")
        session.add_all([tenant_a, tenant_b])
        await session.flush()

        barber_a = Barber(tenant_id=tenant_a.id, name="Barber A")
        service_a = Service(
            tenant_id=tenant_a.id, name="Cut", duration_minutes=60, price=Decimal("100")
        )
        user_a = User(tenant_id=tenant_a.id, telegram_id=700_001, full_name="Client A")

        barber_b = Barber(tenant_id=tenant_b.id, name="Barber B")
        service_b = Service(
            tenant_id=tenant_b.id, name="Cut", duration_minutes=60, price=Decimal("100")
        )
        user_b = User(tenant_id=tenant_b.id, telegram_id=700_002, full_name="Client B")

        session.add_all([barber_a, service_a, user_a, barber_b, service_b, user_b])
        await session.flush()
        for barber in (barber_a, barber_b):
            for weekday in range(7):
                session.add(
                    WorkingSchedule(
                        tenant_id=barber.tenant_id,
                        barber_id=barber.id,
                        weekday=weekday,
                        start_time=time(10, 0),
                        end_time=time(19, 0),
                    )
                )
        await session.commit()
        ids = (
            tenant_a.id,
            tenant_b.id,
            barber_a.id,
            service_a.id,
            user_a.id,
            barber_b.id,
            service_b.id,
            user_b.id,
        )

    (
        tenant_a_id,
        tenant_b_id,
        barber_a_id,
        service_a_id,
        user_a_id,
        barber_b_id,
        service_b_id,
        user_b_id,
    ) = ids
    start = target_slot(settings)

    try:
        async with session_factory() as session:
            user_a_obj = await session.get(User, user_a_id)
            appt_a = await BookingService(session, settings, tenant_a_id).create_appointment(
                user=user_a_obj, barber_id=barber_a_id, service_id=service_a_id, start=start
            )

        # (a) Сервисный слой: BookingService арендатора B не видит барбера/услугу
        # арендатора A вообще — create_appointment падает как "недоступно", а не утекает.
        async with session_factory() as session:
            user_b_obj = await session.get(User, user_b_id)
            with pytest.raises(BookingError):
                await BookingService(session, settings, tenant_b_id).create_appointment(
                    user=user_b_obj,
                    barber_id=barber_a_id,
                    service_id=service_a_id,
                    start=start,
                )

        # (b) Прямой запрос к репозиторию с ЧУЖИМ tenant_id должен вернуть None/[],
        # даже если вызывающий знает точный UUID (проверка на IDOR).
        async with session_factory() as session:
            assert await BarberRepository(session, tenant_b_id).get(barber_a_id) is None
            assert await ServiceRepository(session, tenant_b_id).get(service_a_id) is None
            assert await AppointmentRepository(session, tenant_b_id).get(appt_a.id) is None
            assert await BarberRepository(session, tenant_a_id).get(barber_a_id) is not None

        # (c) Арендатор B может сам забронировать ТОТ ЖЕ слот на своём (так же
        # устроенном) барбере — EXCLUDE-констрейнт и проверка доступности слота
        # корректно работают по барберу, а не случайно шарятся между арендаторами.
        async with session_factory() as session:
            user_b_obj = await session.get(User, user_b_id)
            appt_b = await BookingService(session, settings, tenant_b_id).create_appointment(
                user=user_b_obj, barber_id=barber_b_id, service_id=service_b_id, start=start
            )
            assert appt_b.status == AppointmentStatus.CONFIRMED
    finally:
        async with session_factory() as session:
            for bid in (barber_a_id, barber_b_id):
                await session.execute(delete(Appointment).where(Appointment.barber_id == bid))
                await session.execute(
                    delete(WorkingSchedule).where(WorkingSchedule.barber_id == bid)
                )
            await session.execute(
                delete(Barber).where(Barber.id.in_((barber_a_id, barber_b_id)))
            )
            await session.execute(
                delete(Service).where(Service.id.in_((service_a_id, service_b_id)))
            )
            await session.execute(delete(User).where(User.id.in_((user_a_id, user_b_id))))
            await session.execute(
                delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
            )
            await session.commit()


async def test_service_name_unique_per_tenant_not_globally(session_factory):
    async with session_factory() as session:
        tenant_a = Tenant(name="Tenant A", slug=f"a-{uuid.uuid4().hex[:8]}")
        tenant_b = Tenant(name="Tenant B", slug=f"b-{uuid.uuid4().hex[:8]}")
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id

        try:
            # Одно и то же имя в двух разных арендаторах: должно пройти.
            session.add(
                Service(tenant_id=tenant_a_id, name="Haircut", duration_minutes=30, price=Decimal("50"))
            )
            session.add(
                Service(tenant_id=tenant_b_id, name="Haircut", duration_minutes=30, price=Decimal("50"))
            )
            await session.flush()  # без IntegrityError

            # То же имя дважды в пределах арендатора A: должно упасть.
            session.add(
                Service(tenant_id=tenant_a_id, name="Haircut", duration_minutes=45, price=Decimal("60"))
            )
            with pytest.raises(IntegrityError) as error:
                await session.flush()
            assert "uq_services_tenant_id_name" in str(error.value.orig)
            await session.rollback()
        finally:
            async with session_factory() as cleanup:
                await cleanup.execute(
                    delete(Service).where(Service.tenant_id.in_((tenant_a_id, tenant_b_id)))
                )
                await cleanup.execute(
                    delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
                )
                await cleanup.commit()


# Примечание: настоящая изоляция арендаторов на уровне хендлеров (реального
# апдейта бота) в Phase 1 не проверяется — один Dispatcher/процесс работает
# ровно с одним tenant_id (см. app/main.py). Второй такой процесс появится
# только в фазе мульти-бота; до тех пор изоляция доказывается на уровне
# репозиториев/сервисов выше, где и происходит реальный доступ к БД.


async def test_cancel_frees_the_slot_and_drops_reminders(
    session_factory, settings, tenant_id, fixtures
):
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, hour=15)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        booking = BookingService(session, settings, tenant_id)
        appointment = await booking.create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=start
        )
        cancelled = await booking.cancel_appointment(
            appointment_id=appointment.id,
            cancelled_by=CancelledBy.CLIENT,
            actor_user_id=user.id,
        )
        assert cancelled.status == AppointmentStatus.CANCELLED
        assert cancelled.cancelled_at is not None
        remaining = list(
            await session.scalars(
                select(Notification).where(Notification.appointment_id == appointment.id)
            )
        )
        assert remaining == []

    # Слот снова доступен: EXCLUDE-констрейнт учитывает только подтверждённые записи.
    async with session_factory() as session:
        user = await _load_user(session, user_id)
        again = await BookingService(session, settings, tenant_id).create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=start
        )
        assert again.status == AppointmentStatus.CONFIRMED


async def test_reschedule_moves_appointment(session_factory, settings, tenant_id, fixtures):
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, hour=16)
    new_start = start + timedelta(hours=1)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        booking = BookingService(session, settings, tenant_id)
        appointment = await booking.create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=start
        )
        moved = await booking.reschedule_appointment(
            appointment_id=appointment.id, new_start=new_start, actor_user_id=user.id
        )
        assert moved.starts_at == new_start.astimezone(moved.starts_at.tzinfo)
        assert moved.ends_at - moved.starts_at == timedelta(minutes=60)
        notifications = list(
            await session.scalars(
                select(Notification).where(Notification.appointment_id == appointment.id)
            )
        )
        assert len(notifications) == 2


async def test_appointment_outside_working_hours_is_rejected(
    session_factory, settings, tenant_id, fixtures
):
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, hour=22)  # после 19:00

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(SlotUnavailableError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user, barber_id=barber_id, service_id=service_id, start=start
            )


# --- Права доступа и бизнес-ограничения -------------------------------------
async def test_client_cannot_cancel_someone_elses_appointment(
    session_factory, settings, tenant_id, fixtures
):
    """IDOR: подставленный чужой UUID в callback не должен отменять запись."""
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, hour=11)

    async with session_factory() as session:
        owner = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=owner, barber_id=barber_id, service_id=service_id, start=start
        )
        stranger = User(tenant_id=tenant_id, telegram_id=910_000_001, full_name="Чужой Клиент")
        session.add(stranger)
        await session.commit()
        stranger_id = stranger.id

    async with session_factory() as session:
        with pytest.raises(AppointmentNotFoundError):
            await BookingService(session, settings, tenant_id).cancel_appointment(
                appointment_id=appointment.id,
                cancelled_by=CancelledBy.CLIENT,
                actor_user_id=stranger_id,
            )

    async with session_factory() as session:
        fresh = await session.get(Appointment, appointment.id)
        assert fresh.status == AppointmentStatus.CONFIRMED

    async with session_factory() as session:
        await session.execute(delete(User).where(User.id == stranger_id))
        await session.commit()


async def test_client_cannot_reschedule_someone_elses_appointment(
    session_factory, settings, tenant_id, fixtures
):
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, hour=12)

    async with session_factory() as session:
        owner = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=owner, barber_id=barber_id, service_id=service_id, start=start
        )

    async with session_factory() as session:
        with pytest.raises(AppointmentNotFoundError):
            await BookingService(session, settings, tenant_id).reschedule_appointment(
                appointment_id=appointment.id,
                new_start=start + timedelta(hours=1),
                actor_user_id=uuid.uuid4(),
            )


async def test_admin_can_cancel_any_appointment(session_factory, settings, tenant_id, fixtures):
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, hour=13)

    async with session_factory() as session:
        owner = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=owner, barber_id=barber_id, service_id=service_id, start=start
        )
        cancelled = await BookingService(session, settings, tenant_id).cancel_appointment(
            appointment_id=appointment.id,
            cancelled_by=CancelledBy.ADMIN,
            actor_user_id=None,
        )
        assert cancelled.status == AppointmentStatus.CANCELLED
        assert cancelled.cancelled_by == CancelledBy.ADMIN


async def test_hidden_service_cannot_be_booked_by_stale_callback(
    session_factory, settings, tenant_id, fixtures
):
    """Админ скрыл услугу, а у клиента осталось открытым старое меню."""
    barber_id, service_id, user_id = fixtures
    async with session_factory() as session:
        service = await session.get(Service, service_id)
        service.is_active = False
        await session.commit()

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(BookingError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings, hour=11),
            )

    async with session_factory() as session:
        service = await session.get(Service, service_id)
        service.is_active = True
        await session.commit()


async def test_hidden_barber_cannot_be_booked(session_factory, settings, tenant_id, fixtures):
    barber_id, service_id, user_id = fixtures
    async with session_factory() as session:
        barber = await session.get(Barber, barber_id)
        barber.is_active = False
        await session.commit()

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(BookingError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings, hour=11),
            )

    async with session_factory() as session:
        barber = await session.get(Barber, barber_id)
        barber.is_active = True
        await session.commit()


async def test_booking_in_the_past_is_rejected(session_factory, settings, tenant_id, fixtures):
    barber_id, service_id, user_id = fixtures
    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(SlotUnavailableError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings, days_ahead=-1, hour=12),
            )


async def test_active_appointments_limit_is_enforced(
    session_factory, settings, tenant_id, fixtures
):
    barber_id, service_id, user_id = fixtures
    hours = (10, 11, 12)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        booking = BookingService(session, settings, tenant_id)
        for hour in hours:
            await booking.create_appointment(
                user=user,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings, hour=hour),
            )

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(TooManyActiveAppointmentsError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings, hour=14),
            )


async def test_cancellation_deadline_is_enforced(session_factory, settings, tenant_id, fixtures):
    """До визита меньше CANCEL_MIN_LEAD_MINUTES — клиент отменить уже не может."""
    barber_id, service_id, user_id = fixtures
    soon = now_utc() + timedelta(minutes=90)

    async with session_factory() as session:
        session.add(
            Appointment(
                tenant_id=tenant_id,
                user_id=user_id,
                barber_id=barber_id,
                service_id=service_id,
                starts_at=soon,
                ends_at=soon + timedelta(minutes=60),
                status=AppointmentStatus.CONFIRMED,
                price=Decimal("250.00"),
                duration_minutes=60,
            )
        )
        await session.commit()
        appointment_id = (
            await session.scalars(
                select(Appointment.id).where(Appointment.barber_id == barber_id)
            )
        ).one()

    async with session_factory() as session:
        with pytest.raises(BookingError):
            await BookingService(session, settings, tenant_id).cancel_appointment(
                appointment_id=appointment_id,
                cancelled_by=CancelledBy.CLIENT,
                actor_user_id=user_id,
            )

    # Администратору отмена в последний момент разрешена.
    async with session_factory() as session:
        cancelled = await BookingService(session, settings, tenant_id).cancel_appointment(
            appointment_id=appointment_id,
            cancelled_by=CancelledBy.ADMIN,
        )
        assert cancelled.status == AppointmentStatus.CANCELLED


async def test_day_off_exception_blocks_booking(session_factory, settings, tenant_id, fixtures):
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, days_ahead=3, hour=12)
    day = start.astimezone(settings.tz).date()

    async with session_factory() as session:
        session.add(
            ScheduleException(
                tenant_id=tenant_id, barber_id=barber_id, exception_date=day, is_day_off=True
            )
        )
        await session.commit()

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(SlotUnavailableError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user, barber_id=barber_id, service_id=service_id, start=start
            )

    async with session_factory() as session:
        await session.execute(
            delete(ScheduleException).where(ScheduleException.barber_id == barber_id)
        )
        await session.commit()


# --- Производительность и агрегаты ------------------------------------------
async def test_stats_summary_matches_underlying_data(
    session_factory, settings, tenant_id, fixtures
):
    barber_id, service_id, user_id = fixtures

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        booking = BookingService(session, settings, tenant_id)
        first = await booking.create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=target_slot(settings)
        )
        await booking.create_appointment(
            user=user,
            barber_id=barber_id,
            service_id=service_id,
            start=target_slot(settings, hour=15),
        )
        await booking.cancel_appointment(
            appointment_id=first.id, cancelled_by=CancelledBy.ADMIN
        )

    async with session_factory() as session:
        stats = await StatsService(session, settings, tenant_id).collect()

    assert stats.upcoming_appointments >= 1
    assert stats.cancelled_month >= 1
    assert stats.revenue_month >= 250.0
    assert stats.clients >= 1
    assert any(name.startswith("Тест-услуга") for name, _, _ in stats.top_services)


async def test_stats_is_collected_in_a_few_queries(
    session_factory, settings, tenant_id, fixtures, query_counter
):
    """Раньше сводка стоила 10 запросов — теперь агрегаты считаются одним."""
    async with session_factory() as session:
        query_counter.clear()
        await StatsService(session, settings, tenant_id).collect()

    assert len(query_counter) <= 5, query_counter


async def test_available_days_does_not_query_per_day(
    session_factory, settings, tenant_id, fixtures, query_counter
):
    """Горизонт 14 дней должен грузиться одним пакетом, а не запросом на день."""
    barber_id, _, _ = fixtures
    async with session_factory() as session:
        query_counter.clear()
        days = await ScheduleService(session, settings, tenant_id).available_days(
            barber_id=barber_id, duration_minutes=60
        )

    assert len(days) > 5
    assert len(query_counter) <= 4, query_counter


async def test_booking_keeps_query_count_bounded(
    session_factory, settings, tenant_id, fixtures, query_counter
):
    barber_id, service_id, user_id = fixtures
    async with session_factory() as session:
        user = await _load_user(session, user_id)
        query_counter.clear()
        await BookingService(session, settings, tenant_id).create_appointment(
            user=user,
            barber_id=barber_id,
            service_id=service_id,
            start=target_slot(settings, hour=16),
        )

    inserts = [q for q in query_counter if q.lstrip().upper().startswith("INSERT")]
    # 10 запросов: услуга, барбер, лимит активных записей, advisory-lock клиента,
    # advisory-lock барбера, график, исключения, занятые слоты и два INSERT-а.
    assert len(query_counter) <= 10, query_counter
    # Оба напоминания создаются одним INSERT-ом вместе с записью.
    assert len(inserts) == 2, inserts


async def test_list_upcoming_loads_relations_without_n_plus_one(
    session_factory, settings, tenant_id, fixtures, query_counter
):
    barber_id, service_id, user_id = fixtures
    async with session_factory() as session:
        user = await _load_user(session, user_id)
        booking = BookingService(session, settings, tenant_id)
        for hour in (10, 11):
            await booking.create_appointment(
                user=user,
                barber_id=barber_id,
                service_id=service_id,
                start=target_slot(settings, hour=hour),
            )

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        query_counter.clear()
        appointments = await BookingService(session, settings, tenant_id).list_upcoming_for_user(
            user
        )
        # Обращение к связанным объектам не должно порождать новых запросов.
        rendered = [f"{a.service.name} / {a.barber.name} / {a.user.full_name}" for a in appointments]

    assert len(rendered) == 2
    assert len(query_counter) == 1, query_counter


async def test_busy_barber_lock_fails_fast_with_friendly_error(
    session_factory, settings, tenant_id, fixtures
):
    """Если слот держит чужая транзакция, клиент не висит до statement_timeout."""
    barber_id, service_id, user_id = fixtures
    lock_key = _advisory_lock_key(barber_id)

    async with session_factory() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(CAST(:key AS bigint))"), {"key": lock_key}
        )

        async with session_factory() as session:
            user = await _load_user(session, user_id)
            started = perf_counter()
            with pytest.raises(BookingError) as error:
                await BookingService(session, settings, tenant_id).create_appointment(
                    user=user,
                    barber_id=barber_id,
                    service_id=service_id,
                    start=target_slot(settings, hour=17),
                )
            elapsed = perf_counter() - started

        assert error.value.key == "error.barber_locked"
        assert elapsed < 10, "ожидание блокировки должно быть ограничено"
        await holder.rollback()

    # После освобождения блокировки запись создаётся штатно.
    async with session_factory() as session:
        user = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=user,
            barber_id=barber_id,
            service_id=service_id,
            start=target_slot(settings, hour=17),
        )
        assert appointment.status == AppointmentStatus.CONFIRMED


async def test_booking_beyond_horizon_is_rejected(session_factory, settings, tenant_id, fixtures):
    """Подделанный callback с датой за горизонтом не должен создавать запись."""
    barber_id, service_id, user_id = fixtures
    beyond = target_slot(settings, days_ahead=settings.booking_horizon_days + 5, hour=12)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        with pytest.raises(SlotUnavailableError):
            await BookingService(session, settings, tenant_id).create_appointment(
                user=user, barber_id=barber_id, service_id=service_id, start=beyond
            )


async def test_last_day_of_horizon_is_still_bookable(
    session_factory, settings, tenant_id, fixtures
):
    barber_id, service_id, user_id = fixtures
    last_day = target_slot(settings, days_ahead=settings.booking_horizon_days - 1, hour=12)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=last_day
        )
        assert appointment.status == AppointmentStatus.CONFIRMED


async def test_concurrent_dispatchers_do_not_send_reminder_twice(
    session_factory, settings, tenant_id, fixtures
):
    """Два экземпляра бота (или перезапуск) не должны продублировать напоминание."""
    barber_id, service_id, user_id = fixtures
    start = target_slot(settings, hour=12)

    async with session_factory() as session:
        user = await _load_user(session, user_id)
        appointment = await BookingService(session, settings, tenant_id).create_appointment(
            user=user, barber_id=barber_id, service_id=service_id, start=start
        )

    async with session_factory() as session:
        notification = (
            await session.scalars(
                select(Notification).where(Notification.appointment_id == appointment.id)
            )
        ).first()
        notification.scheduled_for = now_utc() - timedelta(minutes=1)
        await session.commit()

    class CountingBot:
        def __init__(self) -> None:
            self.sent: list[int] = []

        async def send_message(self, chat_id, text, **kwargs):
            await asyncio.sleep(0.05)  # даём второй «реплике» шанс влезть
            self.sent.append(chat_id)

    bot = CountingBot()
    first = NotificationService(bot, session_factory, settings, tenant_id)
    second = NotificationService(bot, session_factory, settings, tenant_id)
    results = await asyncio.gather(first.dispatch_due(), second.dispatch_due())

    assert sum(sent for sent, _ in results) == 1
    assert len(bot.sent) == 1

    # Третий проход уже ничего не находит: статус sent сохранён в БД.
    sent, _ = await first.dispatch_due()
    assert sent == 0
