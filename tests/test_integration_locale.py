"""Интеграционные тесты локализации (Phase 9E) на реальном PostgreSQL:
Tenant.default_language, StaffMember.language, резолюция через
app/services/locale.py, мультибот, уведомления, Tenant Settings, /admin.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import delete

from app.config import Settings
from app.database.models import (
    Appointment,
    AppointmentStatus,
    PlatformOperator,
    PlatformRole,
    Role,
    TelegramBotIdentity,
    Tenant,
)
from app.database.repositories import (
    BranchRepository,
    PlatformOperatorRepository,
    StaffRepository,
    TenantRepository,
    UserRepository,
)
from app.services.notifications import NotificationService
from app.services.onboarding import TenantOnboardingService
from tests.conftest import FLOW_ADMIN_ID, MockedSession

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — интеграционные тесты пропущены"
)


@pytest.fixture(scope="module")
def session_factory(flow_session_factory):
    return flow_session_factory


@pytest.fixture(scope="module")
def dispatcher(flow_dispatcher):
    return flow_dispatcher


OWNER_ID = 990_900_001
MANAGER_ID = 990_900_002
STRANGER_ID = 990_900_999
_next_bot_id = iter(range(962_000_001, 962_100_000))


async def _make_tenant(
    session_factory, *, default_language: str | None = None
) -> tuple[uuid.UUID, int]:
    marker = uuid.uuid4().hex[:8]
    bot_id = next(_next_bot_id)
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name=f"Locale Tenant {marker}", slug=f"locale-{marker}"
        )
        if default_language is not None:
            tenant.default_language = default_language
        session.add(
            TelegramBotIdentity(tenant_id=tenant.id, telegram_bot_id=bot_id, username="lc_bot")
        )
        await StaffRepository(session, tenant.id).create(
            telegram_id=OWNER_ID, role=Role.TENANT_OWNER
        )
        await StaffRepository(session, tenant.id).create(
            telegram_id=MANAGER_ID, role=Role.MANAGER
        )
        await session.commit()
        return tenant.id, bot_id


async def _add_second_bot(session_factory, tenant_id: uuid.UUID) -> int:
    bot_id = next(_next_bot_id)
    async with session_factory() as session:
        session.add(
            TelegramBotIdentity(tenant_id=tenant_id, telegram_bot_id=bot_id, username="lc_bot2")
        )
        await session.commit()
    return bot_id


async def _delete_tenant(session_factory, tenant_id: uuid.UUID) -> None:
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await session.commit()


def _bot(bot_id: int) -> Bot:
    bot = Bot(token=f"{bot_id}:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw", session=MockedSession())
    bot.calls = bot.session.calls
    bot.buttons = bot.session.buttons
    return bot


def make_message(text: str, user_id: int) -> Message:
    return Message(
        message_id=1, date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест", language_code="en"),
        text=text,
    )


def make_callback(data: str, user_id: int) -> CallbackQuery:
    message = Message(
        message_id=2, date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=0, is_bot=True, first_name="Bot"),
        text="prev",
    )
    return CallbackQuery(
        id=uuid.uuid4().hex,
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест", username="tester"),
        chat_instance="x", message=message, data=data,
    )


async def feed(dispatcher, bot: Bot, event) -> list[tuple[str, str | None]]:
    bot.calls.clear()
    bot.buttons.clear()
    update = (
        Update(update_id=1, message=event)
        if isinstance(event, Message)
        else Update(update_id=1, callback_query=event)
    )
    await dispatcher.feed_update(bot, update)
    return list(bot.calls)


def texts(calls: list[tuple[str, str | None]]) -> str:
    return " | ".join(text or "" for _, text in calls)


async def _open_tenant_language_picker(dispatcher, bot: Bot, user_id: int):
    await feed(dispatcher, bot, make_callback("ad:settings:", user_id))
    return await feed(dispatcher, bot, make_callback("ad:tset_lang:", user_id))


async def _pick_tenant_language(dispatcher, bot: Bot, user_id: int, code: str):
    await feed(dispatcher, bot, make_callback(f"ad:tset_lang_set:{code}", user_id))
    return await feed(dispatcher, bot, make_callback("ad:tset_confirm:", user_id))


# --- 13/29. MANAGE_SETTINGS может менять tenant default language; поле
#     отображается в Tenant Settings ------------------------------------------


async def test_owner_can_change_tenant_default_language(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        settings_calls = await feed(dispatcher, bot, make_callback("ad:settings:", OWNER_ID))
        assert "Язык по умолчанию" in texts(settings_calls)

        await _open_tenant_language_picker(dispatcher, bot, OWNER_ID)
        calls = await _pick_tenant_language(dispatcher, bot, OWNER_ID, "ro")
        assert "Română" in texts(calls) or "ro" in texts(calls).lower()

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.default_language == "ro"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 14. Неавторизованная роль (MANAGER) не может изменить --------------------


async def test_manager_cannot_change_tenant_default_language(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_callback("ad:tset_lang:", MANAGER_ID))
        assert "Выберите язык по умолчанию" not in texts(calls)

        await feed(dispatcher, bot, make_callback("ad:tset_lang_set:ro", MANAGER_ID))

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.default_language == "ru"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 15. Tenant A не может изменить язык Tenant B (нет entity_id в callback —
#     весь scoping идёт через DI tenant_id/bot identity) ---------------------


async def test_tenant_isolation_for_default_language(session_factory, dispatcher):
    tenant_a, bot_a_id = await _make_tenant(session_factory)
    tenant_b, _bot_b_id = await _make_tenant(session_factory)
    try:
        bot_a = _bot(bot_a_id)
        await _open_tenant_language_picker(dispatcher, bot_a, OWNER_ID)
        await _pick_tenant_language(dispatcher, bot_a, OWNER_ID, "en")

        async with session_factory() as session:
            reloaded_a = await TenantRepository(session).get(tenant_a)
            reloaded_b = await TenantRepository(session).get(tenant_b)
        assert reloaded_a.default_language == "en"
        assert reloaded_b.default_language == "ru"
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


# --- 16/17. Смена языка арендатора не меняет Branch.timezone/currency -------


async def test_changing_tenant_language_does_not_change_branch_timezone_or_currency(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            branch = await BranchRepository(session, tenant_id).create(
                name="Филиал", timezone="Europe/Chisinau", currency="MDL"
            )
            branch_id = branch.id
            await session.commit()

        bot = _bot(bot_id)
        await _open_tenant_language_picker(dispatcher, bot, OWNER_ID)
        await _pick_tenant_language(dispatcher, bot, OWNER_ID, "ro")

        async with session_factory() as session:
            from app.database.models import Branch as BranchModel

            reloaded_branch = await session.get(BranchModel, branch_id)
        assert reloaded_branch.timezone == "Europe/Chisinau"
        assert reloaded_branch.currency == "MDL"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 18/31. Смена языка арендатора не меняет явное предпочтение сотрудника --


async def test_changing_tenant_language_does_not_change_staff_explicit_language(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        # OWNER_ID сам выставляет себе личный язык.
        await feed(dispatcher, bot, make_callback("ad:my_lang:", OWNER_ID))
        await feed(dispatcher, bot, make_callback("ad:my_lang_set:en", OWNER_ID))

        await _open_tenant_language_picker(dispatcher, bot, OWNER_ID)
        await _pick_tenant_language(dispatcher, bot, OWNER_ID, "ro")

        async with session_factory() as session:
            staff = await StaffRepository(session, tenant_id).get_by_telegram_id(OWNER_ID)
            tenant = await TenantRepository(session).get(tenant_id)
        assert staff.language == "en"
        assert tenant.default_language == "ro"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 19/32. Смена языка арендатора не меняет предпочтение клиента -----------


async def test_changing_tenant_language_does_not_change_customer_language(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            user = await UserRepository(session, tenant_id).get_or_create(
                telegram_id=770_000_001, full_name="Клиент", language_code="en"
            )
            user_id = user.id
            await session.commit()

        bot = _bot(bot_id)
        await _open_tenant_language_picker(dispatcher, bot, OWNER_ID)
        await _pick_tenant_language(dispatcher, bot, OWNER_ID, "ro")

        async with session_factory() as session:
            from app.database.models import User as UserModel

            reloaded_user = await session.get(UserModel, user_id)
        assert reloaded_user.language_code == "en"
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(Appointment).where(Appointment.tenant_id == tenant_id)
            )
        await _delete_tenant(session_factory, tenant_id)


# --- 20/21. Мультибот: один и тот же сотрудник, два бота одного арендатора --


async def test_same_staff_same_language_across_two_bots_when_null(session_factory, dispatcher):
    tenant_id, bot_a_id = await _make_tenant(session_factory, default_language="ro")
    bot_b_id = await _add_second_bot(session_factory, tenant_id)
    try:
        bot_a, bot_b = _bot(bot_a_id), _bot(bot_b_id)
        await feed(dispatcher, bot_a, make_callback("ad:my_lang:", OWNER_ID))
        ro_button_a = next(text for text, data in bot_a.buttons if data == "ad:my_lang_set:ro")
        await feed(dispatcher, bot_b, make_callback("ad:my_lang:", OWNER_ID))
        ro_button_b = next(text for text, data in bot_b.buttons if data == "ad:my_lang_set:ro")
        # NULL StaffMember.language -> наследует Tenant.default_language
        # (ro) одинаково на ОБОИХ ботах одного арендатора — отмечена
        # галочкой на обоих.
        assert ro_button_a.startswith("✅")
        assert ro_button_a == ro_button_b
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_same_staff_explicit_language_across_two_bots(session_factory, dispatcher):
    tenant_id, bot_a_id = await _make_tenant(session_factory)
    bot_b_id = await _add_second_bot(session_factory, tenant_id)
    try:
        bot_a, bot_b = _bot(bot_a_id), _bot(bot_b_id)
        await feed(dispatcher, bot_a, make_callback("ad:my_lang:", OWNER_ID))
        await feed(dispatcher, bot_a, make_callback("ad:my_lang_set:en", OWNER_ID))

        await feed(dispatcher, bot_b, make_callback("ad:my_lang:", OWNER_ID))
        en_button_b = next(text for text, data in bot_b.buttons if data == "ad:my_lang_set:en")
        assert en_button_b.startswith("✅")

        async with session_factory() as session:
            staff = await StaffRepository(session, tenant_id).get_by_telegram_id(OWNER_ID)
        assert staff.language == "en"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 22. Два клиента на одном боте могут иметь разные языки -----------------


async def test_two_customers_same_bot_different_languages(session_factory, dispatcher):
    tenant_id, _bot_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            repo = UserRepository(session, tenant_id)
            await repo.get_or_create(
                telegram_id=770_100_001, full_name="A", language_code="ru"
            )
            await repo.get_or_create(
                telegram_id=770_100_002, full_name="B", language_code="ro"
            )
            await session.commit()
            user_a = await repo.get_by_telegram_id(770_100_001)
            user_b = await repo.get_by_telegram_id(770_100_002)
        assert user_a.language_code == "ru"
        assert user_b.language_code == "ro"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 23. Один Telegram ID в двух арендаторах не приводит к утечке языка -----


async def test_same_telegram_id_two_tenants_no_language_leak(session_factory, dispatcher):
    tenant_a, bot_a_id = await _make_tenant(session_factory, default_language="ru")
    tenant_b, bot_b_id = await _make_tenant(session_factory, default_language="ro")
    shared_id = 770_200_001
    try:
        async with session_factory() as session:
            await UserRepository(session, tenant_a).get_or_create(
                telegram_id=shared_id, full_name="Shared", language_code="en"
            )
            await session.commit()

        bot_a, bot_b = _bot(bot_a_id), _bot(bot_b_id)
        await feed(dispatcher, bot_a, make_message("/start", shared_id))
        await feed(dispatcher, bot_b, make_message("/start", shared_id))

        async with session_factory() as session:
            user_in_a = await UserRepository(session, tenant_a).get_by_telegram_id(shared_id)
            user_in_b = await UserRepository(session, tenant_b).get_by_telegram_id(shared_id)
        assert user_in_a.language_code == "en"
        # Новая строка в tenant_b инициализируется НЕЗАВИСИМО: у клиента нет
        # поддерживаемого Telegram language_code в make_message ("en" —
        # поддерживается, поэтому используется как initial для НОВОЙ строки;
        # ключевая проверка — что это ОТДЕЛЬНАЯ строка, а не утечка "en" из
        # tenant_a через какое-то общее состояние).
        assert user_in_b is not None
        assert user_in_b.id != user_in_a.id
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(Appointment).where(Appointment.tenant_id.in_((tenant_a, tenant_b)))
            )
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


# --- 24/25. Уведомление админам Tenant A/B использует ИХ default_language --


async def _make_appointment_for_notify(session_factory, tenant_id, default_language):
    async with session_factory() as session:
        branch = await BranchRepository(session, tenant_id).create(name="Ф")
        await session.commit()
        branch_id = branch.id
    from app.database.repositories import BarberRepository, ServiceRepository

    async with session_factory() as session:
        barber = await BarberRepository(session, tenant_id).create(name="Барбер")
        service = await ServiceRepository(session, tenant_id).create(
            name="Услуга", duration_minutes=30, price=Decimal("100")
        )
        user = await UserRepository(session, tenant_id).get_or_create(
            telegram_id=770_300_000 + hash((tenant_id, default_language)) % 1000,
            full_name="Клиент",
            language_code="en",
        )
        await session.commit()
        appt = Appointment(
            tenant_id=tenant_id, branch_id=branch_id, user_id=user.id,
            barber_id=barber.id, service_id=service.id,
            starts_at=datetime.now().astimezone() + timedelta(days=1),
            ends_at=datetime.now().astimezone() + timedelta(days=1, hours=1),
            status=AppointmentStatus.CONFIRMED, price=Decimal("100"), duration_minutes=30,
        )
        session.add(appt)
        await session.commit()
        await session.refresh(appt, attribute_names=["user", "branch", "service", "barber"])
        return appt


def _mock_settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
        ADMIN_ID="1",
        TIMEZONE="Europe/Chisinau",
        DEFAULT_LANGUAGE="ru",
    )


async def test_admin_notification_uses_tenant_a_default_language(session_factory):
    tenant_id, _bot_id = await _make_tenant(session_factory, default_language="ro")
    try:
        appt = await _make_appointment_for_notify(session_factory, tenant_id, "ro")
        from unittest.mock import AsyncMock

        bot = AsyncMock()
        service = NotificationService(bot, session_factory, _mock_settings(), tenant_id)
        await service.notify_new_appointment(appt)

        bot.send_message.assert_awaited_once()
        text = bot.send_message.call_args[0][1]
        from app.bot.i18n import t

        assert t("notify.new_appointment", "ro") in text
        # Settings.default_language ("ru") НЕ используется — арендатор "ro".
        assert t("notify.new_appointment", "ru") not in text
    finally:
        async with session_factory() as session:
            await session.execute(delete(Appointment).where(Appointment.tenant_id == tenant_id))
        await _delete_tenant(session_factory, tenant_id)


async def test_admin_notification_uses_tenant_b_default_language(session_factory):
    tenant_id, _bot_id = await _make_tenant(session_factory, default_language="en")
    try:
        appt = await _make_appointment_for_notify(session_factory, tenant_id, "en")
        from unittest.mock import AsyncMock

        bot = AsyncMock()
        service = NotificationService(bot, session_factory, _mock_settings(), tenant_id)
        await service.notify_new_appointment(appt)

        text = bot.send_message.call_args[0][1]
        from app.bot.i18n import t

        assert t("notify.new_appointment", "en") in text
    finally:
        async with session_factory() as session:
            await session.execute(delete(Appointment).where(Appointment.tenant_id == tenant_id))
        await _delete_tenant(session_factory, tenant_id)


# --- 26/27/28. Уведомление клиенту (booking/24h/2h) использует язык клиента,
#     а не settings.default_language, даже когда они различаются -----------


async def test_customer_reminder_uses_customer_language_not_process_default(session_factory):
    tenant_id, _bot_id = await _make_tenant(session_factory, default_language="ru")
    try:
        async with session_factory() as session:
            branch = await BranchRepository(session, tenant_id).create(name="Ф")
            await session.commit()
            branch_id = branch.id
        from app.database.models import Notification, NotificationKind, NotificationStatus
        from app.database.repositories import BarberRepository, ServiceRepository

        async with session_factory() as session:
            barber = await BarberRepository(session, tenant_id).create(name="Барбер")
            service = await ServiceRepository(session, tenant_id).create(
                name="Услуга", duration_minutes=30, price=Decimal("100")
            )
            user = await UserRepository(session, tenant_id).get_or_create(
                telegram_id=770_400_001, full_name="Клиент", language_code="en",
            )
            await session.commit()
            appt = Appointment(
                tenant_id=tenant_id, branch_id=branch_id, user_id=user.id,
                barber_id=barber.id, service_id=service.id,
                starts_at=datetime.now().astimezone() + timedelta(hours=2),
                ends_at=datetime.now().astimezone() + timedelta(hours=3),
                status=AppointmentStatus.CONFIRMED, price=Decimal("100"), duration_minutes=30,
            )
            session.add(appt)
            await session.flush()
            notif = Notification(
                id=uuid.uuid4(), appointment_id=appt.id,
                kind=NotificationKind.REMINDER_2H, status=NotificationStatus.PENDING,
                scheduled_for=datetime.now().astimezone() - timedelta(minutes=1), attempts=0,
            )
            session.add(notif)
            await session.commit()
            notif_id = notif.id

        from unittest.mock import AsyncMock

        bot = AsyncMock()
        # settings.default_language="ru", клиент — "en": не должно совпасть с ru.
        service = NotificationService(bot, session_factory, _mock_settings(), tenant_id)
        sent, errors = await service.dispatch_due()
        assert sent == 1
        assert errors == 0

        text = bot.send_message.call_args[0][1]
        from app.bot.i18n import t

        assert t("notify.reminder_2h", "en") in text
        assert t("notify.reminder_2h", "ru") not in text

        async with session_factory() as session:
            sent_row = await session.get(Notification, notif_id)
        assert sent_row.status == NotificationStatus.SENT
    finally:
        async with session_factory() as session:
            await session.execute(delete(Appointment).where(Appointment.tenant_id == tenant_id))
        await _delete_tenant(session_factory, tenant_id)


# --- 30. Невалидный код языка в forged callback отклоняется -----------------


async def test_forged_language_code_in_callback_is_rejected(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:tset_lang_set:xx", OWNER_ID))

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.default_language == "ru"

        await feed(dispatcher, bot, make_callback("ad:my_lang_set:xx", OWNER_ID))
        async with session_factory() as session:
            staff = await StaffRepository(session, tenant_id).get_by_telegram_id(OWNER_ID)
        assert staff.language is None
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 33. Legacy ADMIN_ID без строки StaffMember/PlatformOperator не получает
#     доступ к админ-панели, несмотря на то что /admin теперь виден всем в
#     меню команд (Phase 9E §16) ----------------------------------------------


_BOOTSTRAP_SEED_ID = 919_000_000_001  # заведомо уникален, не пересекается с другими тестами


async def test_legacy_admin_id_without_staff_row_cannot_access_admin(
    session_factory, dispatcher
):
    """Даже если bootstrap-окно (см. PlatformAuthorizationService.is_operator)
    ещё открыто, ADMIN_ID сам по себе не должен давать доступ к КОНКРЕТНОМУ
    арендатору, где у него нет ни StaffMember, ни PlatformOperator. Тест
    закрывает окно ТОЛЬКО на своё время и только если оно уже не закрыто —
    создаёт/удаляет строго свою собственную строку, чтобы не менять
    глобальное состояние для остальных файлов тестовой сессии (в отличие от
    предыдущей версии этого теста, которая заводила постоянного оператора и
    ломала tests/test_integration_platform.py — исправлено по факту)."""
    tenant_id, bot_id = await _make_tenant(session_factory)
    created_seed = False
    async with session_factory() as session:
        repo = PlatformOperatorRepository(session)
        if not await repo.any_exist():
            await repo.create(telegram_user_id=_BOOTSTRAP_SEED_ID, role=PlatformRole.PLATFORM_ADMIN)
            await session.commit()
            created_seed = True
    try:
        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_message("/admin", FLOW_ADMIN_ID))
        assert "Админ-панель" not in texts(calls)
    finally:
        if created_seed:
            async with session_factory() as session:
                await session.execute(
                    delete(PlatformOperator).where(
                        PlatformOperator.telegram_user_id == _BOOTSTRAP_SEED_ID
                    )
                )
                await session.commit()
        await _delete_tenant(session_factory, tenant_id)


# --- 34. Регистрация команд платформенного бота остаётся изолированной -----


async def test_platform_bot_command_scope_stays_platform_only():
    from unittest.mock import AsyncMock, MagicMock

    from app.main import _validate_platform_bot

    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="platform_bot"))
    bot.set_my_commands = AsyncMock()

    result = await _validate_platform_bot(bot)

    assert result is bot
    bot.set_my_commands.assert_awaited_once()
    sent_commands = bot.set_my_commands.await_args.args[0]
    assert [c.command for c in sent_commands] == ["platform"]


async def test_tenant_bot_admin_command_registered_via_default_scope():
    """Phase 9E §16: /admin регистрируется через BotCommandScopeDefault для
    всех, не через legacy ADMIN_ID per-chat scoping — авторизация
    по-прежнему проверяется IsStaff/RequirePermission на каждом апдейте
    (см. test_legacy_admin_id_without_staff_row_cannot_access_admin)."""
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.types import BotCommandScopeDefault

    from app.main import setup_commands

    bot = MagicMock()
    bot.set_my_commands = AsyncMock()

    await setup_commands(bot)

    bot.set_my_commands.assert_awaited_once()
    sent_commands = bot.set_my_commands.await_args.args[0]
    scope = bot.set_my_commands.await_args.kwargs.get("scope")
    assert any(c.command == "admin" for c in sent_commands)
    assert isinstance(scope, BotCommandScopeDefault)
