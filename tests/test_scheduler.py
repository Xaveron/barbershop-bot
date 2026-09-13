"""Тесты фоновых задач: напоминания и закрытие прошедших записей."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.bot.i18n import t
from app.config import Settings
from app.database import build_session_factory
from app.database.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    Notification,
    NotificationKind,
    NotificationStatus,
    Service,
    User,
    WorkingSchedule,
)
from app.scheduler.jobs import complete_past_appointments, send_due_reminders
from app.services.notifications import NotificationService
from app.utils.dt import now_utc
from tests.conftest import local

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark_db = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан"
)


def make_settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
        ADMIN_ID="999",
        TIMEZONE="Europe/Chisinau",
    )


# --- Unit-тесты NotificationService (без БД) --------------------------------

def _make_appointment_mock(
    *,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
    lang: str = "ru",
    is_blocked: bool = False,
    telegram_id: int = 100,
) -> MagicMock:
    appt = MagicMock(spec=Appointment)
    appt.id = uuid.uuid4()
    appt.status = status
    appt.starts_at = local(2026, 9, 20, 14, 0)
    appt.ends_at = local(2026, 9, 20, 15, 0)
    appt.price = Decimal("250")
    appt.currency = "MDL"
    appt.duration_minutes = 60
    appt.service.name = "Стрижка"
    appt.barber.name = "Иван"
    appt.user.telegram_id = telegram_id
    appt.user.language_code = lang
    appt.user.is_blocked = is_blocked
    return appt


def _make_notification_mock(
    appt: MagicMock,
    kind: NotificationKind = NotificationKind.REMINDER_2H,
) -> MagicMock:
    notif = MagicMock(spec=Notification)
    notif.kind = kind
    notif.appointment = appt
    notif.appointment_id = appt.id
    return notif


async def test_deliver_sends_message_and_marks_sent():
    bot = AsyncMock()
    settings = make_settings()
    service = NotificationService(bot, AsyncMock(), settings)

    appt = _make_appointment_mock(lang="ru")
    notif = _make_notification_mock(appt, NotificationKind.REMINDER_2H)
    repo = AsyncMock()
    users = AsyncMock()

    result = await service._deliver(notif, appt, repo, users)

    assert result is True
    bot.send_message.assert_awaited_once()
    sent_text = bot.send_message.call_args[0][1]
    assert t("notify.reminder_2h", "ru") in sent_text
    repo.mark_sent.assert_awaited_once()
    repo.mark_failed.assert_not_awaited()


async def test_deliver_skips_cancelled_appointment():
    bot = AsyncMock()
    service = NotificationService(bot, AsyncMock(), make_settings())

    appt = _make_appointment_mock(status=AppointmentStatus.CANCELLED)
    notif = _make_notification_mock(appt)
    repo = AsyncMock()

    result = await service._deliver(notif, appt, repo, AsyncMock())

    assert result is False
    bot.send_message.assert_not_awaited()
    repo.drop_pending.assert_awaited_once_with(appt.id)


async def test_deliver_skips_blocked_user():
    bot = AsyncMock()
    service = NotificationService(bot, AsyncMock(), make_settings())

    appt = _make_appointment_mock(is_blocked=True)
    notif = _make_notification_mock(appt)
    repo = AsyncMock()

    result = await service._deliver(notif, appt, repo, AsyncMock())

    assert result is False
    bot.send_message.assert_not_awaited()
    repo.mark_failed.assert_awaited_once()


async def test_deliver_handles_bot_blocked_by_user():
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(
        method=MagicMock(), message="bot was blocked by the user"
    )
    service = NotificationService(bot, AsyncMock(), make_settings())

    appt = _make_appointment_mock()
    notif = _make_notification_mock(appt)
    repo = AsyncMock()
    users = AsyncMock()

    result = await service._deliver(notif, appt, repo, users)

    assert result is False
    users.set_blocked.assert_awaited_once_with(appt.user_id, blocked=True)
    repo.mark_failed.assert_awaited_once()


async def test_deliver_handles_retry_after():
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramRetryAfter(
        method=MagicMock(), message="Too Many Requests: retry after 5", retry_after=5
    )
    service = NotificationService(bot, AsyncMock(), make_settings())

    appt = _make_appointment_mock()
    notif = _make_notification_mock(appt)
    repo = AsyncMock()

    with patch("app.services.notifications.asyncio.sleep", new_callable=AsyncMock):
        result = await service._deliver(notif, appt, repo, AsyncMock())

    assert result is False
    repo.mark_failed.assert_awaited_once()


@pytest.mark.parametrize("lang", ["ru", "ro", "en"])
async def test_reminder_text_uses_client_language(lang):
    bot = AsyncMock()
    service = NotificationService(bot, AsyncMock(), make_settings())

    appt = _make_appointment_mock(lang=lang)
    notif = _make_notification_mock(appt, NotificationKind.REMINDER_24H)
    repo = AsyncMock()

    await service._deliver(notif, appt, repo, AsyncMock())

    sent_text = bot.send_message.call_args[0][1]
    assert t("notify.reminder_24h", lang) in sent_text


async def test_notify_new_appointment_sends_to_admins():
    bot = AsyncMock()
    settings = make_settings()
    service = NotificationService(bot, AsyncMock(), settings)

    appt = _make_appointment_mock()
    appt.user.display_name = "Пётр"
    appt.user.phone = None

    await service.notify_new_appointment(appt)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args[0][1]
    assert t("notify.new_appointment", settings.default_language) in text
    assert "Пётр" in text


async def test_notify_cancelled_by_client_vs_admin():
    bot = AsyncMock()
    settings = make_settings()
    service = NotificationService(bot, AsyncMock(), settings)

    appt = _make_appointment_mock()
    appt.user.display_name = "Пётр"

    await service.notify_cancelled(appt, by_client=True)
    text_client = bot.send_message.call_args[0][1]

    bot.reset_mock()
    await service.notify_cancelled(appt, by_client=False)
    text_admin = bot.send_message.call_args[0][1]

    assert t("notify.cancelled_by_client", settings.default_language) in text_client
    assert t("notify.cancelled_by_admin", settings.default_language) in text_admin
    assert text_client != text_admin


# --- Интеграционные тесты (требуют PostgreSQL) ------------------------------

@pytest.fixture(scope="module")
def db_settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="module")
def session_factory(db_settings):
    engine = create_async_engine(db_settings.database_url, poolclass=NullPool)
    return build_session_factory(engine)


@pytest.fixture
async def db_shop(session_factory):
    """Барбер + услуга + пользователь для интеграционных тестов."""
    marker = uuid.uuid4().hex[:6]
    async with session_factory() as session:
        barber = Barber(name=f"Sched-{marker}")
        service = Service(name=f"Sched-{marker}", duration_minutes=60, price=Decimal("100"))
        user = User(telegram_id=800_000 + int(marker[:4], 16) % 10000, language_code="ru")
        session.add_all([barber, service, user])
        await session.flush()
        session.add(WorkingSchedule(
            barber_id=barber.id, weekday=0,
            start_time=__import__("datetime").time(10, 0),
            end_time=__import__("datetime").time(19, 0),
        ))
        await session.commit()
        ids = (barber.id, service.id, user.id)

    yield ids

    from sqlalchemy import delete as sa_delete
    async with session_factory() as session:
        await session.execute(sa_delete(Appointment).where(Appointment.barber_id == ids[0]))
        await session.execute(sa_delete(WorkingSchedule).where(WorkingSchedule.barber_id == ids[0]))
        await session.execute(sa_delete(Barber).where(Barber.id == ids[0]))
        await session.execute(sa_delete(Service).where(Service.id == ids[1]))
        await session.execute(sa_delete(User).where(User.id == ids[2]))
        await session.commit()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_complete_past_appointments_marks_ended(session_factory, db_shop):
    barber_id, service_id, user_id = db_shop
    now = now_utc()
    past_start = now - timedelta(hours=2)
    past_end = now - timedelta(hours=1)
    future_start = now + timedelta(hours=2)
    future_end = now + timedelta(hours=3)

    async with session_factory() as session:
        past = Appointment(
            user_id=user_id, barber_id=barber_id, service_id=service_id,
            starts_at=past_start, ends_at=past_end,
            status=AppointmentStatus.CONFIRMED,
            price=Decimal("100"), duration_minutes=60,
        )
        future = Appointment(
            user_id=user_id, barber_id=barber_id, service_id=service_id,
            starts_at=future_start, ends_at=future_end,
            status=AppointmentStatus.CONFIRMED,
            price=Decimal("100"), duration_minutes=60,
        )
        session.add_all([past, future])
        await session.commit()
        past_id, future_id = past.id, future.id

    await complete_past_appointments(session_factory)

    async with session_factory() as session:
        refreshed_past = await session.get(Appointment, past_id)
        refreshed_future = await session.get(Appointment, future_id)

    assert refreshed_past.status == AppointmentStatus.COMPLETED
    assert refreshed_future.status == AppointmentStatus.CONFIRMED


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_send_due_reminders_delivers_and_marks_sent(session_factory, db_shop, db_settings):
    barber_id, service_id, user_id = db_shop
    now = now_utc()
    start = now + timedelta(hours=2)

    async with session_factory() as session:
        appt = Appointment(
            user_id=user_id, barber_id=barber_id, service_id=service_id,
            starts_at=start, ends_at=start + timedelta(hours=1),
            status=AppointmentStatus.CONFIRMED,
            price=Decimal("100"), duration_minutes=60,
        )
        session.add(appt)
        await session.flush()
        notif = Notification(
            id=uuid.uuid4(),
            appointment_id=appt.id,
            kind=NotificationKind.REMINDER_2H,
            status=NotificationStatus.PENDING,
            scheduled_for=now - timedelta(minutes=1),
            attempts=0,
        )
        session.add(notif)
        await session.commit()
        notif_id = notif.id

    bot = AsyncMock()
    await send_due_reminders(bot, session_factory, db_settings)

    bot.send_message.assert_awaited_once()

    async with session_factory() as session:
        sent = await session.get(Notification, notif_id)
    assert sent.status == NotificationStatus.SENT
