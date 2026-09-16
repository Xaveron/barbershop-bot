"""Тесты фоновых задач: напоминания и закрытие прошедших записей."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.bot.i18n import t
from app.config import Settings
from app.database import build_session_factory
from app.database.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    BarberBranch,
    Branch,
    Notification,
    NotificationKind,
    NotificationStatus,
    Role,
    Service,
    StaffMember,
    Tenant,
    User,
    WorkingSchedule,
)
from app.database.repositories import StaffRepository
from app.scheduler.jobs import complete_past_appointments, send_due_reminders
from app.services.notifications import NotificationService
from app.utils.dt import now_utc
from tests.conftest import TZ, local

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
# tenant_id здесь не влияет на поведение (репозитории замоканы) — нужен только
# потому что конструктор сервиса требует его.
_UNIT_TENANT_ID = uuid.uuid4()

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
    appt.branch.tz = TZ
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
    service = NotificationService(bot, AsyncMock(), settings, _UNIT_TENANT_ID)

    appt = _make_appointment_mock(lang="ru")
    notif = _make_notification_mock(appt, NotificationKind.REMINDER_2H)
    repo = AsyncMock()
    users = AsyncMock()

    result = await service._deliver(notif, appt, repo, users, "ru")

    assert result is True
    bot.send_message.assert_awaited_once()
    sent_text = bot.send_message.call_args[0][1]
    assert t("notify.reminder_2h", "ru") in sent_text
    repo.mark_sent.assert_awaited_once()
    repo.mark_failed.assert_not_awaited()


async def test_deliver_skips_cancelled_appointment():
    bot = AsyncMock()
    service = NotificationService(bot, AsyncMock(), make_settings(), _UNIT_TENANT_ID)

    appt = _make_appointment_mock(status=AppointmentStatus.CANCELLED)
    notif = _make_notification_mock(appt)
    repo = AsyncMock()

    result = await service._deliver(notif, appt, repo, AsyncMock(), "ru")

    assert result is False
    bot.send_message.assert_not_awaited()
    repo.drop_pending.assert_awaited_once_with(appt.id)


async def test_deliver_skips_blocked_user():
    bot = AsyncMock()
    service = NotificationService(bot, AsyncMock(), make_settings(), _UNIT_TENANT_ID)

    appt = _make_appointment_mock(is_blocked=True)
    notif = _make_notification_mock(appt)
    repo = AsyncMock()

    result = await service._deliver(notif, appt, repo, AsyncMock(), "ru")

    assert result is False
    bot.send_message.assert_not_awaited()
    repo.mark_failed.assert_awaited_once()


async def test_deliver_handles_bot_blocked_by_user():
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(
        method=MagicMock(), message="bot was blocked by the user"
    )
    service = NotificationService(bot, AsyncMock(), make_settings(), _UNIT_TENANT_ID)

    appt = _make_appointment_mock()
    notif = _make_notification_mock(appt)
    repo = AsyncMock()
    users = AsyncMock()

    result = await service._deliver(notif, appt, repo, users, "ru")

    assert result is False
    users.set_blocked.assert_awaited_once_with(appt.user_id, blocked=True)
    repo.mark_failed.assert_awaited_once()


async def test_deliver_handles_retry_after():
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramRetryAfter(
        method=MagicMock(), message="Too Many Requests: retry after 5", retry_after=5
    )
    service = NotificationService(bot, AsyncMock(), make_settings(), _UNIT_TENANT_ID)

    appt = _make_appointment_mock()
    notif = _make_notification_mock(appt)
    repo = AsyncMock()

    with patch("app.services.notifications.asyncio.sleep", new_callable=AsyncMock):
        result = await service._deliver(notif, appt, repo, AsyncMock(), "ru")

    assert result is False
    repo.mark_failed.assert_awaited_once()


@pytest.mark.parametrize("lang", ["ru", "ro", "en"])
async def test_reminder_text_uses_client_language(lang):
    bot = AsyncMock()
    service = NotificationService(bot, AsyncMock(), make_settings(), _UNIT_TENANT_ID)

    appt = _make_appointment_mock(lang=lang)
    notif = _make_notification_mock(appt, NotificationKind.REMINDER_24H)
    repo = AsyncMock()

    await service._deliver(notif, appt, repo, AsyncMock(), lang)

    sent_text = bot.send_message.call_args[0][1]
    assert t("notify.reminder_24h", lang) in sent_text


# notify_new_appointment/notify_cancelled оба заканчиваются в notify_admins,
# который с Phase 9A (§C-2) резолвит получателей через реальную БД
# (StaffRepository.list_notification_recipients), а не settings.admin_ids —
# поэтому оба теста переехали в секцию интеграционных тестов ниже, вместе с
# остальными тестами notify_admins (см. "--- notify_admins: tenant-scoped
# recipients (Phase 9A §C-2) ---").


# --- Интеграционные тесты (требуют PostgreSQL) ------------------------------

@pytest.fixture(scope="module")
def db_settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="module")
def session_factory(db_settings):
    engine = create_async_engine(db_settings.database_url, poolclass=NullPool)
    return build_session_factory(engine)


@pytest.fixture(scope="module")
async def tenant_id(session_factory):
    """Отдельный арендатор на модуль — не пересекается с другими тестами/данными."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        tenant = Tenant(name=f"Sched Tenant {marker}", slug=f"sched-{marker}")
        session.add(tenant)
        await session.commit()
        tid = tenant.id

    yield tid

    from sqlalchemy import delete as sa_delete
    async with session_factory() as session:
        await session.execute(sa_delete(Tenant).where(Tenant.id == tid))
        await session.commit()


@pytest.fixture
async def db_shop(session_factory, tenant_id):
    """Филиал + барбер + услуга + пользователь для интеграционных тестов."""
    marker = uuid.uuid4().hex[:6]
    async with session_factory() as session:
        branch = Branch(tenant_id=tenant_id, name=f"Sched-{marker}")
        barber = Barber(tenant_id=tenant_id, name=f"Sched-{marker}")
        service = Service(
            tenant_id=tenant_id, name=f"Sched-{marker}", duration_minutes=60, price=Decimal("100")
        )
        user = User(
            tenant_id=tenant_id,
            telegram_id=800_000 + int(marker[:4], 16) % 10000,
            full_name="Sched User",
            language_code="ru",
        )
        session.add_all([branch, barber, service, user])
        await session.flush()
        session.add(BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch.id))
        session.add(WorkingSchedule(
            tenant_id=tenant_id,
            barber_id=barber.id, branch_id=branch.id, weekday=0,
            start_time=__import__("datetime").time(10, 0),
            end_time=__import__("datetime").time(19, 0),
        ))
        await session.commit()
        ids = (barber.id, service.id, user.id, branch.id)

    yield ids

    from sqlalchemy import delete as sa_delete
    async with session_factory() as session:
        await session.execute(sa_delete(Appointment).where(Appointment.barber_id == ids[0]))
        await session.execute(sa_delete(WorkingSchedule).where(WorkingSchedule.barber_id == ids[0]))
        await session.execute(sa_delete(BarberBranch).where(BarberBranch.barber_id == ids[0]))
        await session.execute(sa_delete(Barber).where(Barber.id == ids[0]))
        await session.execute(sa_delete(Service).where(Service.id == ids[1]))
        await session.execute(sa_delete(User).where(User.id == ids[2]))
        await session.execute(sa_delete(Branch).where(Branch.id == ids[3]))
        await session.commit()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_complete_past_appointments_marks_ended(session_factory, db_shop, tenant_id):
    barber_id, service_id, user_id, branch_id = db_shop
    now = now_utc()
    past_start = now - timedelta(hours=2)
    past_end = now - timedelta(hours=1)
    future_start = now + timedelta(hours=2)
    future_end = now + timedelta(hours=3)

    async with session_factory() as session:
        past = Appointment(
            tenant_id=tenant_id, branch_id=branch_id,
            user_id=user_id, barber_id=barber_id, service_id=service_id,
            starts_at=past_start, ends_at=past_end,
            status=AppointmentStatus.CONFIRMED,
            price=Decimal("100"), duration_minutes=60,
        )
        future = Appointment(
            tenant_id=tenant_id, branch_id=branch_id,
            user_id=user_id, barber_id=barber_id, service_id=service_id,
            starts_at=future_start, ends_at=future_end,
            status=AppointmentStatus.CONFIRMED,
            price=Decimal("100"), duration_minutes=60,
        )
        session.add_all([past, future])
        await session.commit()
        past_id, future_id = past.id, future.id

    await complete_past_appointments(session_factory, tenant_id)

    async with session_factory() as session:
        refreshed_past = await session.get(Appointment, past_id)
        refreshed_future = await session.get(Appointment, future_id)

    assert refreshed_past.status == AppointmentStatus.COMPLETED
    assert refreshed_future.status == AppointmentStatus.CONFIRMED


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_send_due_reminders_delivers_and_marks_sent(
    session_factory, db_shop, db_settings, tenant_id
):
    barber_id, service_id, user_id, branch_id = db_shop
    now = now_utc()
    start = now + timedelta(hours=2)

    async with session_factory() as session:
        appt = Appointment(
            tenant_id=tenant_id, branch_id=branch_id,
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
    await send_due_reminders(bot, session_factory, db_settings, tenant_id)

    bot.send_message.assert_awaited_once()

    async with session_factory() as session:
        sent = await session.get(Notification, notif_id)
    assert sent.status == NotificationStatus.SENT


# --- notify_admins: tenant-scoped recipients (Phase 9A §C-2) ----------------
# ADMIN_ID/settings.admin_ids больше не участвует в бизнес-уведомлениях
# конкретного арендатора — получатели резолвятся через реальную БД
# (StaffRepository.list_notification_recipients), поэтому эти тесты требуют
# TEST_DATABASE_URL, в отличие от старых unit-тестов notify_new_appointment/
# notify_cancelled (см. комментарий на месте их удаления выше).

_OTHER_ADMIN_ID = 999_999_001  # заведомо НЕ сотрудник ни одного тестового арендатора


async def _make_notify_tenant(session_factory) -> uuid.UUID:
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        tenant = Tenant(name=f"Notify Tenant {marker}", slug=f"notify-{marker}")
        session.add(tenant)
        await session.commit()
        return tenant.id


async def _delete_notify_tenant(session_factory, tenant_id: uuid.UUID) -> None:
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await session.commit()


async def _add_staff(
    session_factory,
    tenant_id: uuid.UUID,
    *,
    telegram_id: int,
    role: Role,
    is_active: bool = True,
) -> None:
    async with session_factory() as session:
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=telegram_id, role=role
        )
        staff.is_active = is_active
        await session.commit()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_notify_new_appointment_sends_to_tenant_owner(session_factory):
    tenant_id = await _make_notify_tenant(session_factory)
    owner_id = 970_800_001
    try:
        await _add_staff(session_factory, tenant_id, telegram_id=owner_id, role=Role.TENANT_OWNER)

        bot = AsyncMock()
        settings = make_settings()
        service = NotificationService(bot, session_factory, settings, tenant_id)
        appt = _make_appointment_mock()
        appt.user.display_name = "Пётр"
        appt.user.phone = None

        await service.notify_new_appointment(appt)

        bot.send_message.assert_awaited_once()
        recipient = bot.send_message.call_args[0][0]
        text = bot.send_message.call_args[0][1]
        assert recipient == owner_id
        assert t("notify.new_appointment", settings.default_language) in text
        assert "Пётр" in text
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(StaffMember.telegram_id == owner_id)
            )
            await session.commit()
        await _delete_notify_tenant(session_factory, tenant_id)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_notify_cancelled_sends_to_tenant_owner(session_factory):
    tenant_id = await _make_notify_tenant(session_factory)
    owner_id = 970_800_002
    try:
        await _add_staff(session_factory, tenant_id, telegram_id=owner_id, role=Role.TENANT_OWNER)

        bot = AsyncMock()
        settings = make_settings()
        service = NotificationService(bot, session_factory, settings, tenant_id)
        appt = _make_appointment_mock()
        appt.user.display_name = "Пётр"

        await service.notify_cancelled(appt, by_client=True)
        text_client = bot.send_message.call_args[0][1]
        recipient_client = bot.send_message.call_args[0][0]

        bot.reset_mock()
        await service.notify_cancelled(appt, by_client=False)
        text_admin = bot.send_message.call_args[0][1]
        recipient_admin = bot.send_message.call_args[0][0]

        assert recipient_client == owner_id
        assert recipient_admin == owner_id
        assert t("notify.cancelled_by_client", settings.default_language) in text_client
        assert t("notify.cancelled_by_admin", settings.default_language) in text_admin
        assert text_client != text_admin
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(StaffMember.telegram_id == owner_id)
            )
            await session.commit()
        await _delete_notify_tenant(session_factory, tenant_id)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_notify_admins_reaches_owner_and_admin_not_manager(session_factory):
    """Recipient policy: активные TENANT_OWNER/TENANT_ADMIN — да,
    MANAGER/RECEPTIONIST/BARBER — нет (см. §C-2)."""
    tenant_id = await _make_notify_tenant(session_factory)
    owner_id, admin_id, manager_id = 970_800_101, 970_800_102, 970_800_103
    try:
        await _add_staff(session_factory, tenant_id, telegram_id=owner_id, role=Role.TENANT_OWNER)
        await _add_staff(session_factory, tenant_id, telegram_id=admin_id, role=Role.TENANT_ADMIN)
        await _add_staff(session_factory, tenant_id, telegram_id=manager_id, role=Role.MANAGER)

        bot = AsyncMock()
        service = NotificationService(bot, session_factory, make_settings(), tenant_id)
        await service.notify_admins("тест")

        notified = {call.args[0] for call in bot.send_message.await_args_list}
        assert notified == {owner_id, admin_id}
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(
                    StaffMember.telegram_id.in_((owner_id, admin_id, manager_id))
                )
            )
            await session.commit()
        await _delete_notify_tenant(session_factory, tenant_id)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_notify_admins_tenant_a_and_tenant_b_are_isolated(session_factory):
    """Пункты 1/2/4 спецификации: уведомление Tenant A доходит только до
    владельца/админа Tenant A; сотрудник Tenant B никогда его не получает —
    и наоборот."""
    tenant_a = await _make_notify_tenant(session_factory)
    tenant_b = await _make_notify_tenant(session_factory)
    owner_a, owner_b = 970_800_201, 970_800_202
    try:
        await _add_staff(session_factory, tenant_a, telegram_id=owner_a, role=Role.TENANT_OWNER)
        await _add_staff(session_factory, tenant_b, telegram_id=owner_b, role=Role.TENANT_OWNER)

        bot_a = AsyncMock()
        await NotificationService(bot_a, session_factory, make_settings(), tenant_a).notify_admins(
            "для A"
        )
        notified_a = {call.args[0] for call in bot_a.send_message.await_args_list}
        assert notified_a == {owner_a}

        bot_b = AsyncMock()
        await NotificationService(bot_b, session_factory, make_settings(), tenant_b).notify_admins(
            "для B"
        )
        notified_b = {call.args[0] for call in bot_b.send_message.await_args_list}
        assert notified_b == {owner_b}
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(StaffMember.telegram_id.in_((owner_a, owner_b)))
            )
            await session.commit()
        await _delete_notify_tenant(session_factory, tenant_a)
        await _delete_notify_tenant(session_factory, tenant_b)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_notify_admins_skips_inactive_recipients(session_factory):
    tenant_id = await _make_notify_tenant(session_factory)
    inactive_owner_id = 970_800_301
    try:
        await _add_staff(
            session_factory,
            tenant_id,
            telegram_id=inactive_owner_id,
            role=Role.TENANT_OWNER,
            is_active=False,
        )

        bot = AsyncMock()
        service = NotificationService(bot, session_factory, make_settings(), tenant_id)
        await service.notify_admins("тест")

        bot.send_message.assert_not_awaited()
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(StaffMember.telegram_id == inactive_owner_id)
            )
            await session.commit()
        await _delete_notify_tenant(session_factory, tenant_id)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_notify_admins_empty_recipients_is_safe(session_factory):
    """Пункт 5: пустой список получателей (арендатор без активного
    владельца/админа) не должен ронять notify_admins."""
    tenant_id = await _make_notify_tenant(session_factory)
    try:
        bot = AsyncMock()
        service = NotificationService(bot, session_factory, make_settings(), tenant_id)
        await service.notify_admins("тест")
        bot.send_message.assert_not_awaited()
    finally:
        await _delete_notify_tenant(session_factory, tenant_id)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_notify_admins_ignores_admin_id_entirely(session_factory):
    """Пункт 7: settings.admin_ids не участвует в резолюции получателей —
    ADMIN_ID, у которого нет строки StaffMember в этом арендаторе, не получает
    уведомление, даже если формально настроен в окружении."""
    tenant_id = await _make_notify_tenant(session_factory)
    owner_id = 970_800_401
    try:
        await _add_staff(session_factory, tenant_id, telegram_id=owner_id, role=Role.TENANT_OWNER)

        settings = Settings(
            BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
            DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
            ADMIN_ID=str(_OTHER_ADMIN_ID),
            TIMEZONE="Europe/Chisinau",
        )
        bot = AsyncMock()
        service = NotificationService(bot, session_factory, settings, tenant_id)
        await service.notify_admins("тест")

        notified = {call.args[0] for call in bot.send_message.await_args_list}
        assert notified == {owner_id}
        assert _OTHER_ADMIN_ID not in notified
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(StaffMember.telegram_id == owner_id)
            )
            await session.commit()
        await _delete_notify_tenant(session_factory, tenant_id)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан")
async def test_send_due_reminders_error_notifies_tenant_owner_not_admin_id(
    session_factory, db_shop, tenant_id
):
    """Пункт 6: ошибка доставки напоминаний тоже резолвит получателей через
    tenant staff, а не settings.admin_ids — используем общий (module-scoped)
    db_shop/tenant_id планировщика, добавляя владельца поверх."""
    barber_id, service_id, user_id, branch_id = db_shop
    owner_id = 970_800_501
    await _add_staff(session_factory, tenant_id, telegram_id=owner_id, role=Role.TENANT_OWNER)
    try:
        now = now_utc()
        start = now + timedelta(hours=2)
        async with session_factory() as session:
            appt = Appointment(
                tenant_id=tenant_id, branch_id=branch_id,
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

        bot = AsyncMock()
        # Первый вызов (само напоминание) падает с необработанным в _deliver
        # исключением -> dispatch_due засчитывает errors=1 -> notify_admins
        # вызывается; второй вызов (уведомление владельцу об ошибке) уже
        # проходит нормально.
        bot.send_message.side_effect = [RuntimeError("simulated failure"), None]
        settings = Settings(
            BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
            DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
            ADMIN_ID=str(_OTHER_ADMIN_ID),
            TIMEZONE="Europe/Chisinau",
        )
        # Первый send_message (напоминание) падает -> errors=1 -> notify_admins.
        # Второй send_message (само уведомление об ошибке) должен уйти
        # реальному владельцу арендатора, а не _OTHER_ADMIN_ID.
        await send_due_reminders(bot, session_factory, settings, tenant_id)

        recipients = [call.args[0] for call in bot.send_message.await_args_list]
        assert owner_id in recipients
        assert _OTHER_ADMIN_ID not in recipients
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(StaffMember.telegram_id == owner_id)
            )
            await session.commit()
