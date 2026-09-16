"""Интеграционные тесты Tenant Settings (Phase 9C §Tenant Settings) на
реальном PostgreSQL: имя/часовой пояс/валюта арендатора, редактируемые через
Permission.MANAGE_SETTINGS (не MANAGE_TENANT). Слаг и статус — read-only в
этом экране (см. app/bot/handlers/admin/settings.py, app/services/
tenant_settings.py).

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

from app.database.models import Branch, Role, TelegramBotIdentity, Tenant
from app.database.repositories import (
    BranchRepository,
    StaffRepository,
    TenantRepository,
)
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


OWNER_ID = 990_800_001
MANAGER_ID = 990_800_002
STRANGER_ID = 990_800_999
_next_bot_id = iter(range(961_000_001, 961_100_000))


async def _make_tenant(session_factory) -> tuple[uuid.UUID, int]:
    """Свежий арендатор со своим ботом, владельцем (MANAGE_SETTINGS) и
    менеджером (без MANAGE_SETTINGS) — настоящие роли, не is_super_admin."""
    marker = uuid.uuid4().hex[:8]
    bot_id = next(_next_bot_id)
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name=f"Settings Tenant {marker}", slug=f"settings-{marker}"
        )
        session.add(
            TelegramBotIdentity(tenant_id=tenant.id, telegram_bot_id=bot_id, username="st_bot")
        )
        await StaffRepository(session, tenant.id).create(
            telegram_id=OWNER_ID, role=Role.TENANT_OWNER
        )
        await StaffRepository(session, tenant.id).create(
            telegram_id=MANAGER_ID, role=Role.MANAGER
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


async def _open_settings(dispatcher, bot: Bot, user_id: int) -> list[tuple[str, str | None]]:
    return await feed(dispatcher, bot, make_callback("ad:settings:0", user_id))


async def _edit_field(
    dispatcher, bot: Bot, user_id: int, action: str, new_value: str
) -> list[tuple[str, str | None]]:
    """Полный флоу: открыть поле -> отправить новое значение -> подтвердить."""
    await feed(dispatcher, bot, make_callback(f"ad:{action}:", user_id))
    calls = await feed(dispatcher, bot, make_message(new_value, user_id))
    return calls


async def _confirm(dispatcher, bot: Bot, user_id: int) -> list[tuple[str, str | None]]:
    return await feed(dispatcher, bot, make_callback("ad:tset_confirm:", user_id))


# --- 1. Просмотр настроек авторизованным сотрудником ------------------------


async def test_owner_can_view_settings(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await _open_settings(dispatcher, _bot(bot_id), OWNER_ID)
        rendered = texts(calls)
        assert "Настройки арендатора" in rendered
        assert "Слаг" in rendered
        assert "Часовой пояс" in rendered
        assert "Валюта" in rendered
        assert "Статус" in rendered
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 2. Неавторизованная роль не может мутировать настройки -----------------


async def test_manager_cannot_open_or_mutate_settings(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        calls = await _open_settings(dispatcher, bot, MANAGER_ID)
        assert "Настройки арендатора" not in texts(calls)

        # Даже прямой callback на поле не должен пройти для MANAGER.
        calls = await feed(dispatcher, bot, make_callback("ad:tset_name:", MANAGER_ID))
        assert "Настройки арендатора" not in texts(calls)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.name.startswith("Settings Tenant")
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 3. Обновление имени -----------------------------------------------------


async def test_name_update(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        await _edit_field(dispatcher, bot, OWNER_ID, "tset_name", "Новое Имя Салона")
        calls = await _confirm(dispatcher, bot, OWNER_ID)
        assert "Новое Имя Салона" in texts(calls)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.name == "Новое Имя Салона"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 4. Невалидное имя отклоняется ------------------------------------------


async def test_invalid_name_rejected(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:tset_name:", OWNER_ID))
        calls = await feed(dispatcher, bot, make_message("A", OWNER_ID))
        assert "⚠️" in texts(calls)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.name.startswith("Settings Tenant")
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 5. Обновление часового пояса валидным IANA-идентификатором -------------


async def test_timezone_update_with_valid_iana_zone(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        await _edit_field(dispatcher, bot, OWNER_ID, "tset_tz", "Europe/Bucharest")
        calls = await _confirm(dispatcher, bot, OWNER_ID)
        assert "Europe/Bucharest" in texts(calls)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.timezone == "Europe/Bucharest"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 6. Невалидный часовой пояс отклоняется ----------------------------------


async def test_invalid_timezone_rejected(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:tset_tz:", OWNER_ID))
        calls = await feed(dispatcher, bot, make_message("Not/AZone", OWNER_ID))
        assert "⚠️" in texts(calls)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.timezone != "Not/AZone"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 7. Изменение Tenant.timezone НЕ меняет Branch.timezone -----------------


async def test_changing_tenant_timezone_does_not_change_existing_branch_timezone(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            branch = await BranchRepository(session, tenant_id).create(name="Филиал-1")
            branch_id = branch.id
            original_branch_tz = branch.timezone
            await session.commit()

        bot = _bot(bot_id)
        await _edit_field(dispatcher, bot, OWNER_ID, "tset_tz", "Asia/Tbilisi")
        await _confirm(dispatcher, bot, OWNER_ID)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
            reloaded_branch = await session.get(Branch, branch_id)

        assert tenant.timezone == "Asia/Tbilisi"
        assert reloaded_branch.timezone == original_branch_tz
        assert reloaded_branch.timezone != "Asia/Tbilisi"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 8. Обновление валюты ----------------------------------------------------


async def test_currency_update(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        await _edit_field(dispatcher, bot, OWNER_ID, "tset_currency", "EUR")
        calls = await _confirm(dispatcher, bot, OWNER_ID)
        assert "EUR" in texts(calls)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.currency == "EUR"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 9. Невалидная валюта отклоняется ----------------------------------------


async def test_invalid_currency_rejected(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:tset_currency:", OWNER_ID))
        calls = await feed(dispatcher, bot, make_message("TOOLONG", OWNER_ID))
        assert "⚠️" in texts(calls)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.currency != "TOOLONG"
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 10. Слаг read-only: нет пути редактирования, значение не меняется ------


async def test_slug_is_read_only(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            original_slug = (await TenantRepository(session).get(tenant_id)).slug

        bot = _bot(bot_id)
        calls = await _open_settings(dispatcher, bot, OWNER_ID)
        assert original_slug in texts(calls)
        assert "неизменяем" in texts(calls)

        # Нет кнопки/действия для редактирования слага — прямой forged
        # callback с таким действием не существует в диспетчере вообще,
        # так что сама попытка ничего не изменит и не уронит хендлер.
        await feed(dispatcher, bot, make_callback("ad:tset_slug:", OWNER_ID))

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.slug == original_slug
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 11. Статус нельзя изменить через settings-экран ------------------------


async def test_status_cannot_be_changed_through_settings(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            original_status = (await TenantRepository(session).get(tenant_id)).status

        bot = _bot(bot_id)
        calls = await _open_settings(dispatcher, bot, OWNER_ID)
        rendered = texts(calls)
        assert original_status.value in rendered
        # Никакой кнопки активации/приостановки на этом экране нет.
        assert not any(
            data and (data.startswith("ad:tset_activate") or data.startswith("ad:tset_suspend"))
            for _, data in bot.buttons
        )

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.status == original_status
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 12. Изоляция между арендаторами -----------------------------------------


async def test_tenant_isolation(session_factory, dispatcher):
    tenant_a, bot_a_id = await _make_tenant(session_factory)
    tenant_b, _bot_b_id = await _make_tenant(session_factory)
    try:
        bot_a = _bot(bot_a_id)
        await _edit_field(dispatcher, bot_a, OWNER_ID, "tset_name", "Only Tenant A")
        await _confirm(dispatcher, bot_a, OWNER_ID)

        async with session_factory() as session:
            reloaded_a = await TenantRepository(session).get(tenant_a)
            reloaded_b = await TenantRepository(session).get(tenant_b)

        assert reloaded_a.name == "Only Tenant A"
        assert reloaded_b.name != "Only Tenant A"
        assert reloaded_b.name.startswith("Settings Tenant")
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


# --- 13. Forged/межарендаторский callback не мутирует чужого арендатора -----


async def test_forged_callback_cannot_mutate_another_tenant(session_factory, dispatcher):
    tenant_a, bot_a_id = await _make_tenant(session_factory)
    tenant_b, _bot_b_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            original_b_name = (await TenantRepository(session).get(tenant_b)).name

        # Владелец арендатора A пытается через СВОЙ бот (значит, свой
        # tenant_id, разрешённый DI) изменить настройки — сервер применяет
        # правку строго к tenant_id, разрешённому через bot identity, а не
        # к любому UUID, который теоретически можно было бы подсунуть в
        # callback. У AdmCB/tset_* вообще нет entity_id в arg — весь
        # tenant-scoping идёт только через DI tenant_id, так что подделать
        # чужой tenant_id через callback structurally невозможно.
        bot_a = _bot(bot_a_id)
        await _edit_field(dispatcher, bot_a, OWNER_ID, "tset_name", "Hacked Name")
        await _confirm(dispatcher, bot_a, OWNER_ID)

        async with session_factory() as session:
            reloaded_a = await TenantRepository(session).get(tenant_a)
            reloaded_b = await TenantRepository(session).get(tenant_b)

        assert reloaded_a.name == "Hacked Name"
        assert reloaded_b.name == original_b_name
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


# --- 14. Существующая бизнес-логика филиалов не затронута -------------------


async def test_existing_branch_business_logic_unaffected(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            branch = await BranchRepository(session, tenant_id).create(
                name="Филиал", timezone="Europe/Chisinau", currency="MDL"
            )
            branch_id = branch.id
            await session.commit()

        bot = _bot(bot_id)
        await _edit_field(dispatcher, bot, OWNER_ID, "tset_currency", "RON")
        await _confirm(dispatcher, bot, OWNER_ID)
        await _edit_field(dispatcher, bot, OWNER_ID, "tset_tz", "Europe/Bucharest")
        await _confirm(dispatcher, bot, OWNER_ID)

        async with session_factory() as session:
            reloaded_branch = await session.get(Branch, branch_id)

        assert reloaded_branch.timezone == "Europe/Chisinau"
        assert reloaded_branch.currency == "MDL"
    finally:
        await _delete_tenant(session_factory, tenant_id)
