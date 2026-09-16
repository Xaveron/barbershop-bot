"""Регрессионные тесты для находок Phase 9G (финальный аудит SaaS-архитектуры):

1. admin/branches.py::toggle_branch не проверял MAX_BRANCHES при
   реактивации — единственный из трёх toggle-хендлеров (филиалы/барберы/
   услуги) без этой защиты (см. admin/barbers.py::toggle_barber,
   admin/services.py::toggle_service, оба уже её имели, Phase 9B §M-2).
   Эксплойт на тарифе Free (max_branches=1): скрыть филиал → создать новый
   (лимит проверяет только активные, проходит) → показать скрытый снова →
   2 активных филиала при лимите 1.

2. admin/services.py::add_service_description брал валюту из process-wide
   settings.default_currency вместо Tenant.currency — тот же класс бага,
   что settings.default_language до Phase 9E, но для валюты новых услуг.
   У Service нет способа отредактировать валюту после создания
   (admin_service_kb), так что ошибка на этом шаге неисправима из UI.

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

from app.database.models import Role, TelegramBotIdentity, Tenant
from app.database.repositories import BranchRepository, ServiceRepository, StaffRepository
from app.services.onboarding import TenantOnboardingService
from app.services.tenant_settings import TenantSettingsService
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


OWNER_ID = 990_970_001
_next_bot_id = iter(range(964_000_001, 964_100_000))


async def _make_tenant(session_factory) -> tuple[uuid.UUID, int]:
    """Свежий арендатор на тарифе Free по умолчанию (см.
    TenantOnboardingService.create_tenant -> DEFAULT_PLAN_CODE = "free")."""
    marker = uuid.uuid4().hex[:8]
    bot_id = next(_next_bot_id)
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name=f"Phase9G {marker}", slug=f"phase9g-{marker}"
        )
        session.add(
            TelegramBotIdentity(tenant_id=tenant.id, telegram_bot_id=bot_id, username="p9g_bot")
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


# --- 1. Реактивация филиала не может обойти MAX_BRANCHES (Free plan: 1) ----


async def test_branch_reactivation_cannot_bypass_max_branches_limit(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        async with session_factory() as session:
            first_branch = await BranchRepository(session, tenant_id).create(name="Первый")
            first_branch_id = first_branch.id
            await session.commit()

        bot = _bot(bot_id)

        # Скрыть единственный филиал -> активных филиалов 0.
        await feed(dispatcher, bot, make_callback(f"ad:brh:{first_branch_id}", OWNER_ID))
        toggle_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:brh_toggle:")
        )
        await feed(dispatcher, bot, make_callback(toggle_button, OWNER_ID))
        async with session_factory() as session:
            reloaded_first = await BranchRepository(session, tenant_id).get(first_branch_id)
        assert reloaded_first.is_active is False

        # Создать НОВЫЙ филиал через полный админ-флоу — лимит (1) считает
        # только активные, сейчас 0, поэтому проходит.
        await feed(dispatcher, bot, make_callback("ad:brh_add:", OWNER_ID))
        await feed(dispatcher, bot, make_message("Второй", OWNER_ID))
        await feed(dispatcher, bot, make_message("-", OWNER_ID))

        async with session_factory() as session:
            total_after_second = await BranchRepository(session, tenant_id).count_all()
        assert total_after_second == 2  # первый (скрытый) + второй (активный)

        # Попытка реактивировать ПЕРВЫЙ (скрытый) филиал теперь должна быть
        # отклонена: активных филиалов уже 1 (второй), лимит Free — 1.
        await feed(dispatcher, bot, make_callback(f"ad:brh:{first_branch_id}", OWNER_ID))
        toggle_button_again = next(
            data for _, data in bot.buttons if data and data.startswith("ad:brh_toggle:")
        )
        await feed(dispatcher, bot, make_callback(toggle_button_again, OWNER_ID))

        async with session_factory() as session:
            branches = await BranchRepository(session, tenant_id).list_all()
            active_count = sum(1 for b in branches if b.is_active)
        # Главная проверка регресса: НЕ должно стать 2 активных филиала на
        # тарифе с лимитом 1 — до фикса реактивация проходила безоговорочно.
        assert active_count == 1
        async with session_factory() as session:
            still_hidden = await BranchRepository(session, tenant_id).get(first_branch_id)
        assert still_hidden.is_active is False
    finally:
        await _delete_tenant(session_factory, tenant_id)


# --- 2. Новая услуга наследует Tenant.currency, а не settings.default_currency ---


async def test_new_service_uses_tenant_currency_not_process_default(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        # Арендатор явно меняет валюту через Tenant Settings — процесс-wide
        # settings.default_currency (в тестовом окружении — "MDL", см.
        # tests/conftest.py::flow_settings) при этом НЕ меняется.
        async with session_factory() as session:
            await TenantSettingsService(session, tenant_id).update_currency(
                currency="RON", actor_telegram_id=OWNER_ID
            )

        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:svc_add:", OWNER_ID))
        await feed(dispatcher, bot, make_message("Стрижка", OWNER_ID))
        await feed(dispatcher, bot, make_message("30", OWNER_ID))
        await feed(dispatcher, bot, make_message("100", OWNER_ID))
        calls = await feed(dispatcher, bot, make_message("-", OWNER_ID))

        assert "RON" in texts(calls)
        assert "MDL" not in texts(calls)

        async with session_factory() as session:
            services = await ServiceRepository(session, tenant_id).list_all()
        assert len(services) == 1
        assert services[0].currency == "RON"
    finally:
        await _delete_tenant(session_factory, tenant_id)
