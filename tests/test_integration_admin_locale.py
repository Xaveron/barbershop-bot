"""Интеграционные тесты локализации tenant-admin UI (Phase 9F, Task 8).

Дополняет tests/test_integration_locale.py (Phase 9E — модель данных и
резолюция) и tests/test_admin_locale_static.py (статический аудит) —
здесь проверяется, что РЕАЛЬНЫЙ текст, который видит сотрудник в диалоге,
действительно рендерится на правильном языке.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import delete

from app.bot.i18n import t
from app.database.models import Role, StaffMember, TelegramBotIdentity, Tenant
from app.database.repositories import StaffRepository
from app.services.onboarding import TenantOnboardingService
from tests.conftest import MockedSession

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


OWNER_ID = 990_950_001
_next_bot_id = iter(range(963_000_001, 963_100_000))


async def _make_tenant(
    session_factory, *, default_language: str = "ru"
) -> tuple[uuid.UUID, int]:
    marker = uuid.uuid4().hex[:8]
    bot_id = next(_next_bot_id)
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name=f"AdminLocale {marker}", slug=f"adminlocale-{marker}"
        )
        tenant.default_language = default_language
        session.add(
            TelegramBotIdentity(tenant_id=tenant.id, telegram_bot_id=bot_id, username="al_bot")
        )
        await StaffRepository(session, tenant.id).create(
            telegram_id=OWNER_ID, role=Role.TENANT_OWNER
        )
        await session.commit()
        return tenant.id, bot_id


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
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест"),
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


def buttons_text(bot: Bot) -> str:
    return " | ".join(text for text, _ in bot.buttons)


# --- 1/2/3. Tenant default RU/RO/EN -> admin UI RU/RO/EN --------------------


@pytest.mark.parametrize("lang", ["ru", "ro", "en"])
async def test_admin_menu_matches_tenant_default_language(session_factory, dispatcher, lang):
    tenant_id, bot_id = await _make_tenant(session_factory, default_language=lang)
    try:
        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_message("/admin", OWNER_ID))
        assert t("admin.menu.title", lang) in texts(calls)
        assert t("admin.menu.services", lang) in buttons_text(bot)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 4. Staff override RU on a RO-default tenant -> admin UI RU ------------


async def test_staff_override_ru_on_ro_tenant(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory, default_language="ro")
    try:
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:my_lang:", OWNER_ID))
        await feed(dispatcher, bot, make_callback("ad:my_lang_set:ru", OWNER_ID))

        calls = await feed(dispatcher, bot, make_message("/admin", OWNER_ID))
        assert t("admin.menu.title", "ru") in texts(calls)
        assert t("admin.menu.title", "ro") not in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 5. Staff override EN on a RU-default tenant -> admin UI EN ------------


async def test_staff_override_en_on_ru_tenant(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory, default_language="ru")
    try:
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:my_lang:", OWNER_ID))
        await feed(dispatcher, bot, make_callback("ad:my_lang_set:en", OWNER_ID))

        calls = await feed(dispatcher, bot, make_message("/admin", OWNER_ID))
        assert t("admin.menu.title", "en") in texts(calls)
        assert t("admin.menu.title", "ru") not in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 6. NULL staff language inherits tenant default -------------------------


async def test_null_staff_language_inherits_tenant_default(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory, default_language="ro")
    try:
        async with session_factory() as session:
            staff = await StaffRepository(session, tenant_id).get_by_telegram_id(OWNER_ID)
            assert staff.language is None

        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_message("/admin", OWNER_ID))
        assert t("admin.menu.title", "ro") in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 7. Two staff of the same tenant can see different localized admin UI --


async def test_two_staff_same_tenant_different_languages(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory, default_language="ru")
    admin_id = 990_950_101
    try:
        async with session_factory() as session:
            await StaffRepository(session, tenant_id).create(
                telegram_id=admin_id, role=Role.TENANT_ADMIN
            )
            await session.commit()

        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:my_lang:", admin_id))
        await feed(dispatcher, bot, make_callback("ad:my_lang_set:en", admin_id))

        owner_calls = await feed(dispatcher, bot, make_message("/admin", OWNER_ID))
        admin_calls = await feed(dispatcher, bot, make_message("/admin", admin_id))

        assert t("admin.menu.title", "ru") in texts(owner_calls)
        assert t("admin.menu.title", "en") in texts(admin_calls)
    finally:
        async with session_factory() as session:
            await session.execute(delete(StaffMember).where(StaffMember.telegram_id == admin_id))
            await session.commit()
        await _delete_tenant(session_factory, tenant_id)


# --- 8. Two tenants use different defaults without leakage ------------------


async def test_two_tenants_different_defaults_no_leakage(session_factory, dispatcher):
    tenant_a, bot_a_id = await _make_tenant(session_factory, default_language="ro")
    tenant_b, bot_b_id = await _make_tenant(session_factory, default_language="en")
    try:
        bot_a, bot_b = _bot(bot_a_id), _bot(bot_b_id)
        calls_a = await feed(dispatcher, bot_a, make_message("/admin", OWNER_ID))
        calls_b = await feed(dispatcher, bot_b, make_message("/admin", OWNER_ID))

        assert t("admin.menu.title", "ro") in texts(calls_a)
        assert t("admin.menu.title", "en") in texts(calls_b)
        assert t("admin.menu.title", "en") not in texts(calls_a)
        assert t("admin.menu.title", "ro") not in texts(calls_b)
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


# --- 9. Pagination labels localized ------------------------------------------


async def test_pagination_add_button_localized(session_factory, dispatcher):
    from app.database.repositories import BranchRepository

    tenant_id, bot_id = await _make_tenant(session_factory, default_language="en")
    try:
        async with session_factory() as session:
            for i in range(3):
                await BranchRepository(session, tenant_id).create(name=f"Branch-{i}")
            await session.commit()

        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_callback("ad:branches:0", OWNER_ID))
        assert t("admin.branches.add", "en") in buttons_text(bot)
        assert t("admin.branches.list_title", "en", total=3) in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 10. Confirmations/errors localized -------------------------------------


async def test_confirmation_and_error_localized(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory, default_language="ro")
    try:
        bot = _bot(bot_id)
        # Ошибка: несуществующий филиал.
        calls = await feed(
            dispatcher, bot, make_callback(f"ad:brh:{uuid.uuid4()}", OWNER_ID)
        )
        assert t("admin.branch.not_found", "ro") in texts(calls)

        # Подтверждение: создание филиала доходит до карточки на нужном языке.
        await feed(dispatcher, bot, make_callback("ad:brh_add:", OWNER_ID))
        await feed(dispatcher, bot, make_message("Filiala Nouă", OWNER_ID))
        calls = await feed(dispatcher, bot, make_message("Str. Centrală 1", OWNER_ID))
        assert t("admin.branch.created", "ro") in texts(calls)
        assert t("admin.branch.status_active", "ro") in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 11. callback_data остаётся языко-независимым ---------------------------


async def test_callback_data_is_language_independent(session_factory, dispatcher):
    tenant_ru, bot_ru_id = await _make_tenant(session_factory, default_language="ru")
    tenant_en, bot_en_id = await _make_tenant(session_factory, default_language="en")
    try:
        bot_ru, bot_en = _bot(bot_ru_id), _bot(bot_en_id)
        await feed(dispatcher, bot_ru, make_message("/admin", OWNER_ID))
        await feed(dispatcher, bot_en, make_message("/admin", OWNER_ID))

        data_ru = {data for _, data in bot_ru.buttons}
        data_en = {data for _, data in bot_en.buttons}
        # Callback data (не текст кнопок) идентична независимо от языка —
        # это машинные идентификаторы действий, а не переводимый текст.
        assert data_ru == data_en
    finally:
        await _delete_tenant(session_factory, tenant_ru)
        await _delete_tenant(session_factory, tenant_en)


# --- 12. Ни один путь admin UI не использует settings.default_language -----
#     после StaffContext (проверено конкретным сценарием: settings.
#     default_language «ru» в тестовом окружении, а вывод — на языке
#     арендатора/сотрудника, который явно другой). ---------------------------


async def test_admin_ui_ignores_process_wide_default_language(session_factory, dispatcher):
    """flow_settings (см. tests/conftest.py) везде использует
    DEFAULT_LANGUAGE, эффективно «ru» — если бы админ-хендлер хоть где-то
    читал settings.default_language вместо staff_lang, этот тест увидел бы
    русский текст вместо английского."""
    tenant_id, bot_id = await _make_tenant(session_factory, default_language="en")
    try:
        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_message("/admin", OWNER_ID))
        assert t("admin.menu.title", "en") in texts(calls)
        assert t("admin.menu.title", "ru") not in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 13. Все использованные ключи локализации существуют в ru/ro/en --------
# Покрыто отдельным быстрым (без БД) статическим тестом:
# tests/test_admin_locale_static.py::test_every_t_call_key_exists_in_all_locales
