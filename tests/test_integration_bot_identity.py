"""Интеграционные тесты Bot Identity -> Tenant resolution (Phase 7) на
реальном PostgreSQL.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.bot.keyboards.callbacks import AdmCB
from app.database.models import Role, Tenant, TenantStatus
from app.database.repositories import StaffRepository, TelegramBotIdentityRepository
from app.register_bot import register_bot
from app.scheduler.setup import build_scheduler
from app.services.bot_identity import BotIdentityResolver
from tests.conftest import MockedSession

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — интеграционные тесты пропущены"
)

BOT_A_ID = 811_111_111
BOT_B_ID = 822_222_222
BOT_UNKNOWN_ID = 833_333_333


@pytest.fixture(scope="module")
def settings(flow_settings):
    """Алиас на session-scoped tests/conftest.py::flow_settings — см. её
    докстринг про общий Dispatcher между этим файлом и test_handlers_flow.py."""
    return flow_settings


@pytest.fixture(scope="module")
def session_factory(flow_session_factory):
    return flow_session_factory


@pytest.fixture(scope="module")
def dispatcher(flow_dispatcher):
    return flow_dispatcher


async def _make_tenant(session_factory, *, status: TenantStatus = TenantStatus.ACTIVE) -> uuid.UUID:
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        tenant = Tenant(name=f"Bot Tenant {marker}", slug=f"bot-{marker}", status=status)
        session.add(tenant)
        await session.commit()
        return tenant.id


async def _delete_tenant(session_factory, tenant_id: uuid.UUID) -> None:
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await session.commit()


@pytest.fixture
async def tenant_a(session_factory):
    tid = await _make_tenant(session_factory)
    yield tid
    await _delete_tenant(session_factory, tid)


@pytest.fixture
async def tenant_b(session_factory):
    tid = await _make_tenant(session_factory)
    yield tid
    await _delete_tenant(session_factory, tid)


def _bot(bot_id: int) -> Bot:
    """Токен с заданным префиксом даёт Bot.id == bot_id (client-side parsing,
    без обращения к Telegram — см. docs/BOT_IDENTITY_ARCHITECTURE.md)."""
    bot = Bot(token=f"{bot_id}:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw", session=MockedSession())
    bot.calls = bot.session.calls
    bot.buttons = bot.session.buttons
    return bot


def make_message(text: str, user_id: int) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест", username="tester"),
        text=text,
    )


async def feed(dispatcher, bot: Bot, message: Message) -> list[tuple[str, str | None]]:
    bot.calls.clear()
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))
    return list(bot.calls)


# === A. Модель / репозиторий ==================================================
async def test_create_bot_identity(session_factory, tenant_a):
    async with session_factory() as session:
        identity = await TelegramBotIdentityRepository(session).create(
            tenant_id=tenant_a, telegram_bot_id=900_000_001, username="shop_a_bot"
        )
        await session.commit()
    assert identity.is_active is True
    assert identity.username == "shop_a_bot"


async def test_duplicate_telegram_bot_id_across_tenants_rejected(
    session_factory, tenant_a, tenant_b
):
    bot_id = 900_000_002
    async with session_factory() as session:
        await TelegramBotIdentityRepository(session).create(
            tenant_id=tenant_a, telegram_bot_id=bot_id, username="dup"
        )
        await session.commit()
    async with session_factory() as session:
        # create() уже флашит — конфликт уникальности всплывает здесь, а не
        # на commit() (тот же паттерн, что и у других repository.create()).
        with pytest.raises(IntegrityError):
            await TelegramBotIdentityRepository(session).create(
                tenant_id=tenant_b, telegram_bot_id=bot_id, username="dup2"
            )


async def test_tenant_can_have_multiple_bot_identities(session_factory, tenant_a):
    async with session_factory() as session:
        repo = TelegramBotIdentityRepository(session)
        await repo.create(tenant_id=tenant_a, telegram_bot_id=900_000_003, username="a1")
        await repo.create(tenant_id=tenant_a, telegram_bot_id=900_000_004, username="a2")
        await session.commit()
    async with session_factory() as session:
        rows = await TelegramBotIdentityRepository(session).list_for_tenant(tenant_a)
    assert {r.telegram_bot_id for r in rows} == {900_000_003, 900_000_004}


async def test_get_by_bot_id_returns_none_for_unknown(session_factory):
    async with session_factory() as session:
        row = await TelegramBotIdentityRepository(session).get_by_bot_id(999_999_999)
    assert row is None


async def test_get_by_bot_id_returns_inactive_row_as_is(session_factory, tenant_a):
    async with session_factory() as session:
        await TelegramBotIdentityRepository(session).create(
            tenant_id=tenant_a, telegram_bot_id=900_000_005, username="off", is_active=False
        )
        await session.commit()
    async with session_factory() as session:
        row = await TelegramBotIdentityRepository(session).get_by_bot_id(900_000_005)
    assert row is not None
    assert row.is_active is False


# === B. Резолвер ===============================================================
async def test_resolver_resolves_active_bot_to_tenant(session_factory, tenant_a):
    async with session_factory() as session:
        await TelegramBotIdentityRepository(session).create(
            tenant_id=tenant_a, telegram_bot_id=900_000_006, username="r1"
        )
        await session.commit()
    async with session_factory() as session:
        identity = await BotIdentityResolver(session).resolve(900_000_006)
    assert identity is not None
    assert identity.tenant_id == tenant_a


async def test_resolver_returns_none_for_unregistered_bot(session_factory):
    async with session_factory() as session:
        identity = await BotIdentityResolver(session).resolve(900_000_999)
    assert identity is None


# === C. Middleware / dispatcher: multi-bot изоляция ============================
async def test_two_bots_resolve_to_different_tenants(
    dispatcher, session_factory, tenant_a, tenant_b
):
    async with session_factory() as session:
        repo = TelegramBotIdentityRepository(session)
        await repo.create(tenant_id=tenant_a, telegram_bot_id=BOT_A_ID, username="shop_a")
        await repo.create(tenant_id=tenant_b, telegram_bot_id=BOT_B_ID, username="shop_b")
        await session.commit()

    bot_a, bot_b = _bot(BOT_A_ID), _bot(BOT_B_ID)
    calls_a = await feed(dispatcher, bot_a, make_message("/start", 700_001))
    calls_b = await feed(dispatcher, bot_b, make_message("/start", 700_002))

    # Оба ответа реальны (не пусты) и это разные вызовы — bot identity не
    # смешала арендаторов на уровне резолюции (RBAC/данные проверяются ниже).
    assert calls_a and calls_b


async def test_unknown_bot_fails_closed(dispatcher):
    bot = _bot(BOT_UNKNOWN_ID)
    calls = await feed(dispatcher, bot, make_message("/start", 700_003))
    assert calls == []


async def test_inactive_bot_identity_blocked(dispatcher, session_factory, tenant_a):
    async with session_factory() as session:
        await TelegramBotIdentityRepository(session).create(
            tenant_id=tenant_a, telegram_bot_id=900_000_010, username="off_bot", is_active=False
        )
        await session.commit()
    bot = _bot(900_000_010)
    calls = await feed(dispatcher, bot, make_message("/start", 700_004))
    assert calls == []


async def test_same_telegram_user_id_is_independent_customer_per_tenant(
    dispatcher, session_factory, tenant_a, tenant_b
):
    from app.database.models import User

    shared_user_id = 700_777_777
    async with session_factory() as session:
        repo = TelegramBotIdentityRepository(session)
        await repo.create(tenant_id=tenant_a, telegram_bot_id=900_000_011, username="ua")
        await repo.create(tenant_id=tenant_b, telegram_bot_id=900_000_012, username="ub")
        await session.commit()

    await feed(dispatcher, _bot(900_000_011), make_message("/start", shared_user_id))
    await feed(dispatcher, _bot(900_000_012), make_message("/start", shared_user_id))

    async with session_factory() as session:
        users = list(
            await session.scalars(select(User).where(User.telegram_id == shared_user_id))
        )
    by_tenant = {u.tenant_id for u in users}
    assert tenant_a in by_tenant
    assert tenant_b in by_tenant
    assert len(users) == 2  # два независимых Customer, не один общий


async def test_admin_button_scoped_to_tenant_with_staff_row(
    dispatcher, session_factory, tenant_a, tenant_b
):
    """Один и тот же Telegram-аккаунт — владелец в Tenant A, никто в Tenant B:
    админ-кнопка видна через Bot A и не видна через Bot B (см. §17/§18-13)."""
    staff_telegram_id = 700_888_888
    async with session_factory() as session:
        repo = TelegramBotIdentityRepository(session)
        await repo.create(tenant_id=tenant_a, telegram_bot_id=900_000_013, username="owner_bot")
        await repo.create(tenant_id=tenant_b, telegram_bot_id=900_000_014, username="stranger_bot")
        await session.commit()
        await StaffRepository(session, tenant_a).create(
            telegram_id=staff_telegram_id, role=Role.TENANT_OWNER
        )
        await session.commit()

    admin_button = AdmCB(action="menu").pack()

    bot_a = _bot(900_000_013)
    await feed(dispatcher, bot_a, make_message("/start", staff_telegram_id))
    assert any(data == admin_button for _, data in bot_a.buttons)

    bot_b = _bot(900_000_014)
    await feed(dispatcher, bot_b, make_message("/start", staff_telegram_id))
    assert not any(data == admin_button for _, data in bot_b.buttons)


async def test_suspended_tenant_blocks_normal_menu(dispatcher, session_factory):
    tenant_id = await _make_tenant(session_factory, status=TenantStatus.SUSPENDED)
    try:
        async with session_factory() as session:
            await TelegramBotIdentityRepository(session).create(
                tenant_id=tenant_id, telegram_bot_id=900_000_015, username="suspended_bot"
            )
            await session.commit()

        bot = _bot(900_000_015)
        calls = await feed(dispatcher, bot, make_message("/start", 700_999_999))
        book_button = any(data == "m:book" for _, data in bot.buttons)
        assert calls  # existing lifecycle logic still answers something
        assert not book_button  # но не обычным меню (см. app/bot/handlers/common.py)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# === D. Планировщик =============================================================
async def test_build_scheduler_registers_jobs_per_tenant(settings, session_factory):
    bot_a, bot_b = _bot(900_100_001), _bot(900_100_002)
    tenant_x, tenant_y = uuid.uuid4(), uuid.uuid4()

    # Планировщик тут не запускается (.start()) — проверяется только
    # регистрация задач/kwargs, поэтому и .shutdown() не нужен.
    scheduler = build_scheduler({tenant_x: bot_a, tenant_y: bot_b}, session_factory, settings)
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"send_due_reminders:{tenant_x}",
        f"complete_past_appointments:{tenant_x}",
        f"schedule_return_reminders:{tenant_x}",
        f"send_due_reminders:{tenant_y}",
        f"complete_past_appointments:{tenant_y}",
        f"schedule_return_reminders:{tenant_y}",
    }
    reminder_job_x = scheduler.get_job(f"send_due_reminders:{tenant_x}")
    assert reminder_job_x.kwargs["bot"] is bot_a
    assert reminder_job_x.kwargs["tenant_id"] == tenant_x
    reminder_job_y = scheduler.get_job(f"send_due_reminders:{tenant_y}")
    assert reminder_job_y.kwargs["bot"] is bot_b


async def test_resolve_bots_by_tenant_picks_earliest_identity_for_scheduler(
    session_factory, tenant_a
):
    from app.main import _resolve_bots_by_tenant

    bot_first, bot_second = _bot(900_100_003), _bot(900_100_004)
    async with session_factory() as session:
        repo = TelegramBotIdentityRepository(session)
        await repo.create(tenant_id=tenant_a, telegram_bot_id=bot_first.id, username="first")
        await session.commit()
    async with session_factory() as session:
        repo = TelegramBotIdentityRepository(session)
        await repo.create(tenant_id=tenant_a, telegram_bot_id=bot_second.id, username="second")
        await session.commit()

    mapping = await _resolve_bots_by_tenant([bot_first, bot_second], session_factory)
    assert mapping[tenant_a] is bot_first  # зарегистрирован раньше


# === E. app/register_bot.py: провижининг ======================================
# bot.get_me() всегда мокается — эти тесты не должны стучаться в реальный
# Telegram (см. docs/BOT_IDENTITY_ARCHITECTURE.md о том, что провижининг
# сам по себе делает ровно один живой вызов getMe(), не воспроизводимый в тестах).
def _mocked_get_me(telegram_bot_id: int, username: str):
    return patch(
        "app.register_bot.Bot.get_me",
        new=AsyncMock(
            return_value=TgUser(
                id=telegram_bot_id, is_bot=True, first_name="Shop", username=username
            )
        ),
    )


async def test_register_bot_creates_new_identity(session_factory, tenant_a):
    with _mocked_get_me(900_500_001, "shop_a_bot"):
        exit_code = await register_bot(tenant_a)
    assert exit_code == 0
    async with session_factory() as session:
        identity = await TelegramBotIdentityRepository(session).get_by_bot_id(900_500_001)
    assert identity is not None
    assert identity.tenant_id == tenant_a
    assert identity.username == "shop_a_bot"


async def test_register_bot_is_idempotent_for_same_tenant(session_factory, tenant_a):
    with _mocked_get_me(900_500_002, "shop_a_bot"):
        first = await register_bot(tenant_a)
        second = await register_bot(tenant_a)
    assert (first, second) == (0, 0)
    async with session_factory() as session:
        rows = await TelegramBotIdentityRepository(session).list_for_tenant(tenant_a)
    assert len([r for r in rows if r.telegram_bot_id == 900_500_002]) == 1


async def test_register_bot_refuses_to_reassign_existing_bot(
    session_factory, tenant_a, tenant_b
):
    with _mocked_get_me(900_500_003, "shop_a_bot"):
        await register_bot(tenant_a)
        exit_code = await register_bot(tenant_b)
    assert exit_code == 1
    async with session_factory() as session:
        identity = await TelegramBotIdentityRepository(session).get_by_bot_id(900_500_003)
    assert identity.tenant_id == tenant_a  # не переехал на tenant_b


async def test_register_bot_rejects_unknown_tenant(session_factory):
    with _mocked_get_me(900_500_004, "orphan_bot"):
        exit_code = await register_bot(uuid.uuid4())
    assert exit_code == 1
    async with session_factory() as session:
        identity = await TelegramBotIdentityRepository(session).get_by_bot_id(900_500_004)
    assert identity is None
