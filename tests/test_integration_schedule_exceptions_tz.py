"""Интеграционные тесты branch-local timezone + authorization для
исключений графика (Phase 9B §M-3) на реальном PostgreSQL: show_exceptions/
add_exception_date должны использовать Branch.timezone выбранного филиала,
а не settings.tz, и никогда не доверять branch_id без переверки через
resolve_accessible_branch_ids.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import delete, select

from app.database.models import (
    Branch,
    Role,
    ScheduleException,
    StaffMember,
    TelegramBotIdentity,
    Tenant,
)
from app.database.repositories import BranchRepository, ScheduleRepository, StaffRepository
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


OWNER_ID = 990_500_001
MANAGER_ID = 990_500_002
_next_bot_id = iter(range(945_000_001, 945_100_000))

# 01:00 UTC: у филиала Etc/GMT+12 (UTC-12) местное "сегодня" — 14 июня, а у
# settings.tz по умолчанию (Europe/Chisinau, летом UTC+3) — уже 15 июня.
# Ровно на этом расхождении и построена проверка "не settings.tz".
FIXED_NOW = datetime(2026, 6, 15, 1, 0, tzinfo=UTC)
BRANCH_LOCAL_TODAY = "14.06.2026"


async def _make_tenant_with_branches(session_factory) -> dict:
    marker = uuid.uuid4().hex[:8]
    bot_id = next(_next_bot_id)
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name=f"Exc Tenant {marker}", slug=f"exc-{marker}"
        )
        session.add(
            TelegramBotIdentity(tenant_id=tenant.id, telegram_bot_id=bot_id, username="exc_bot")
        )
        await StaffRepository(session, tenant.id).create(
            telegram_id=OWNER_ID, role=Role.TENANT_OWNER
        )
        branch_tz = Branch(tenant_id=tenant.id, name=f"TZ-{marker}", timezone="Etc/GMT+12")
        branch_normal = Branch(tenant_id=tenant.id, name=f"Normal-{marker}")
        session.add_all([branch_tz, branch_normal])
        await session.commit()
        return {
            "tenant_id": tenant.id, "bot_id": bot_id,
            "branch_tz": branch_tz.id, "branch_normal": branch_normal.id,
        }


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
    update = (
        Update(update_id=1, message=event)
        if isinstance(event, Message)
        else Update(update_id=1, callback_query=event)
    )
    await dispatcher.feed_update(bot, update)
    return list(bot.calls)


def texts(calls: list[tuple[str, str | None]]) -> str:
    return " | ".join(text or "" for _, text in calls)


async def _enter_branch_exception_date_step(
    dispatcher, bot, user_id: int, branch_id: uuid.UUID
) -> None:
    """Разгоняет /admin-flow до шага «введите дату» для конкретного филиала,
    минуя пикер барбера/филиала — использует «весь филиал» (global) и
    напрямую подделывает exc_pick_branch, как сделал бы легитимный клик."""
    await feed(dispatcher, bot, make_callback("ad:exc_add:", user_id))
    await feed(dispatcher, bot, make_callback("ad:exc_who:all", user_id))
    await feed(dispatcher, bot, make_callback(f"ad:exc_pick_branch:{branch_id}", user_id))


# === 1/2. Branch-local "сегодня", не settings.tz (UTC midnight boundary) ===
async def test_exception_date_uses_branch_timezone_not_settings_tz(session_factory, dispatcher):
    """FIXED_NOW=01:00 UTC: у Etc/GMT+12 "сегодня" — 14 июня, у settings.tz
    по умолчанию (Europe/Chisinau) — уже 15 июня. Дата 14.06.2026 должна
    пройти валидацию (она "сегодня" по branch.tz), хотя старый код
    (settings.tz) отверг бы её как "уже прошла" (15 июня > 14 июня)."""
    shop = await _make_tenant_with_branches(session_factory)
    bot = _bot(shop["bot_id"])
    try:
        with patch("app.utils.dt.now_utc", return_value=FIXED_NOW):
            await _enter_branch_exception_date_step(dispatcher, bot, OWNER_ID, shop["branch_tz"])
            calls = await feed(dispatcher, bot, make_message(BRANCH_LOCAL_TODAY, OWNER_ID))
        # Дата принята -> следующий шаг (выбор режима "выходной"/"часы"),
        # а не ошибка валидации "дата уже прошла".
        assert "Что делаем?" in texts(calls)
        assert "уже прошла" not in texts(calls)
    finally:
        await _delete_tenant(session_factory, shop["tenant_id"])


async def test_exception_date_rejects_past_date_using_correct_branch_boundary(
    session_factory, dispatcher
):
    """Зеркальная проверка: дата ПЕРЕД branch-local "сегодня" (13 июня, при
    branch-local "сегодня" 14 июня) по-прежнему корректно отвергается —
    фикс не разучился отклонять реально прошедшие даты, просто считает
    границу по правильному часовому поясу."""
    shop = await _make_tenant_with_branches(session_factory)
    bot = _bot(shop["bot_id"])
    try:
        with patch("app.utils.dt.now_utc", return_value=FIXED_NOW):
            await _enter_branch_exception_date_step(dispatcher, bot, OWNER_ID, shop["branch_tz"])
            calls = await feed(dispatcher, bot, make_message("13.06.2026", OWNER_ID))
        assert "уже прошла" in texts(calls)
    finally:
        await _delete_tenant(session_factory, shop["tenant_id"])


async def test_show_exceptions_lists_exception_created_on_branch_local_today(
    session_factory, dispatcher
):
    """show_exceptions тоже должен видеть исключение, датированное "сегодня"
    по branch.tz, даже если по settings.tz эта дата уже "прошла" (была бы
    отфильтрована горизонтом date_from=today, посчитанным в settings.tz)."""
    shop = await _make_tenant_with_branches(session_factory)
    bot = _bot(shop["bot_id"])
    try:
        async with session_factory() as session:
            saved = await ScheduleRepository(session, shop["tenant_id"]).upsert_exception(
                branch_id=shop["branch_tz"],
                barber_id=None,
                exception_date=datetime.strptime(BRANCH_LOCAL_TODAY, "%d.%m.%Y").date(),
                is_day_off=True,
            )
            assert saved is not None
            await session.commit()

        with patch("app.utils.dt.now_utc", return_value=FIXED_NOW):
            calls = await feed(dispatcher, bot, make_callback("ad:exceptions:", OWNER_ID))
        assert "14.06.2026" in texts(calls)
    finally:
        await _delete_tenant(session_factory, shop["tenant_id"])


# === 3. Unauthorized branch rejected ========================================
async def test_forged_branch_pick_rejected_for_restricted_manager(session_factory, dispatcher):
    shop = await _make_tenant_with_branches(session_factory)
    bot = _bot(shop["bot_id"])
    async with session_factory() as session:
        manager = await StaffRepository(session, shop["tenant_id"]).create(
            telegram_id=MANAGER_ID, role=Role.MANAGER
        )
        await session.commit()
        await BranchRepository(session, shop["tenant_id"]).assign_staff(
            staff_member_id=manager.id, branch_id=shop["branch_normal"]
        )
        await session.commit()
    try:
        await feed(dispatcher, bot, make_callback("ad:exc_add:", MANAGER_ID))
        await feed(dispatcher, bot, make_callback("ad:exc_who:all", MANAGER_ID))
        calls = await feed(
            dispatcher, bot,
            make_callback(f"ad:exc_pick_branch:{shop['branch_tz']}", MANAGER_ID),
        )
        assert "Недостаточно прав или филиал недоступен." in texts(calls)
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(StaffMember.telegram_id == MANAGER_ID)
            )
            await session.commit()
        await _delete_tenant(session_factory, shop["tenant_id"])


# === 4. Exception belongs to the selected branch, not another one ==========
async def test_exception_is_saved_against_the_selected_branch(session_factory, dispatcher):
    shop = await _make_tenant_with_branches(session_factory)
    bot = _bot(shop["bot_id"])
    try:
        await _enter_branch_exception_date_step(dispatcher, bot, OWNER_ID, shop["branch_normal"])
        await feed(dispatcher, bot, make_message("31.12.2026", OWNER_ID))
        await feed(dispatcher, bot, make_callback("ad:exc_mode:off", OWNER_ID))

        async with session_factory() as session:
            saved = await session.scalar(
                select(ScheduleException).where(
                    ScheduleException.tenant_id == shop["tenant_id"],
                )
            )
        assert saved is not None
        assert saved.branch_id == shop["branch_normal"]
        assert saved.branch_id != shop["branch_tz"]
    finally:
        await _delete_tenant(session_factory, shop["tenant_id"])


# === 5. Cross-tenant branch impossible ======================================
async def test_cross_tenant_branch_cannot_be_selected(session_factory, dispatcher):
    shop_a = await _make_tenant_with_branches(session_factory)
    shop_b = await _make_tenant_with_branches(session_factory)
    bot_a = _bot(shop_a["bot_id"])
    try:
        await feed(dispatcher, bot_a, make_callback("ad:exc_add:", OWNER_ID))
        await feed(dispatcher, bot_a, make_callback("ad:exc_who:all", OWNER_ID))
        calls = await feed(
            dispatcher, bot_a,
            make_callback(f"ad:exc_pick_branch:{shop_b['branch_normal']}", OWNER_ID),
        )
        assert "Недостаточно прав или филиал недоступен." in texts(calls)

        async with session_factory() as session:
            leaked = await session.scalar(
                select(ScheduleException).where(
                    ScheduleException.tenant_id == shop_a["tenant_id"],
                    ScheduleException.branch_id == shop_b["branch_normal"],
                )
            )
        assert leaked is None
    finally:
        await _delete_tenant(session_factory, shop_a["tenant_id"])
        await _delete_tenant(session_factory, shop_b["tenant_id"])
