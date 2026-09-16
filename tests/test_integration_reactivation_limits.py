"""Интеграционные тесты reactivation limit enforcement (Phase 9B §M-2) на
реальном PostgreSQL: toggle_barber/toggle_service должны проверять лимит
тарифа (LimitService.assert_can_create) при реактивации так же, как при
создании — деактивированные ресурсы не должны позволять обойти
MAX_BARBERS/MAX_SERVICES циклом скрыть → создать новый → показать старый.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import delete

from app.database.models import BarberBranch, Branch, Role, TelegramBotIdentity, Tenant
from app.database.repositories import BarberRepository, ServiceRepository, StaffRepository
from app.services.billing import SubscriptionService
from app.services.onboarding import TenantOnboardingService
from tests.conftest import MockedSession

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — интеграционные тесты пропущены"
)


@pytest.fixture(scope="module")
def settings(flow_settings):
    return flow_settings


@pytest.fixture(scope="module")
def session_factory(flow_session_factory):
    return flow_session_factory


@pytest.fixture(scope="module")
def dispatcher(flow_dispatcher):
    return flow_dispatcher


OWNER_ID = 990_400_001
_next_bot_id = iter(range(940_000_001, 940_100_000))


async def _make_tenant(session_factory) -> tuple[uuid.UUID, int, uuid.UUID]:
    """Свежий арендатор (Free-план, MAX_BARBERS=2/MAX_SERVICES=10 — см.
    миграцию 0010) со своим ботом, владельцем и одним активным филиалом —
    независимый от других тестов лимит usage. Филиал обязателен: "бронируемый"
    барбер для LimitService._count_bookable_barbers — это активный барбер,
    привязанный хотя бы к одному активному филиалу (см. app/services/billing.py)."""
    marker = uuid.uuid4().hex[:8]
    bot_id = next(_next_bot_id)
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name=f"Limit Tenant {marker}", slug=f"limit-{marker}"
        )
        session.add(
            TelegramBotIdentity(tenant_id=tenant.id, telegram_bot_id=bot_id, username="lb_bot")
        )
        await StaffRepository(session, tenant.id).create(
            telegram_id=OWNER_ID, role=Role.TENANT_OWNER
        )
        branch = Branch(tenant_id=tenant.id, name="Main")
        session.add(branch)
        await session.commit()
        return tenant.id, bot_id, branch.id


async def _delete_tenant(session_factory, tenant_id: uuid.UUID) -> None:
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await session.commit()


def _bot(bot_id: int) -> Bot:
    bot = Bot(token=f"{bot_id}:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw", session=MockedSession())
    bot.calls = bot.session.calls
    bot.buttons = bot.session.buttons
    return bot


def make_callback(data: str, user_id: int) -> CallbackQuery:
    message = Message(
        message_id=2,
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=0, is_bot=True, first_name="Bot"),
        text="prev",
    )
    return CallbackQuery(
        id=uuid.uuid4().hex,
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест", username="tester"),
        chat_instance="x",
        message=message,
        data=data,
    )


async def feed(dispatcher, bot: Bot, callback: CallbackQuery) -> list[tuple[str, str | None]]:
    bot.calls.clear()
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=callback))
    return list(bot.calls)


def texts(calls: list[tuple[str, str | None]]) -> str:
    return " | ".join(text or "" for _, text in calls)


async def _add_barber(
    session_factory, tenant_id, branch_id, *, name: str, is_active: bool = True
):
    async with session_factory() as session:
        barber = await BarberRepository(session, tenant_id).create(name=name)
        barber.is_active = is_active
        session.add(BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch_id))
        await session.commit()
        return barber.id


async def _add_service(session_factory, tenant_id, *, name: str, is_active: bool = True):
    async with session_factory() as session:
        service = await ServiceRepository(session, tenant_id).create(
            name=name, duration_minutes=30, price=Decimal("100")
        )
        service.is_active = is_active
        await session.commit()
        return service.id


async def _set_plan(session_factory, tenant_id, *, plan_code: str) -> None:
    async with session_factory() as session:
        await SubscriptionService(session, tenant_id).change_plan(
            plan_code=plan_code, actor_telegram_id=OWNER_ID
        )


# === Барберы (MAX_BARBERS = 2 на Free) ======================================
async def test_barber_reactivation_under_limit_succeeds(session_factory, dispatcher):
    tenant_id, bot_id, branch_id = await _make_tenant(session_factory)
    barber_id = await _add_barber(session_factory, tenant_id, branch_id, name="Solo", is_active=False)
    try:
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback(f"ad:brb_toggle:{barber_id}", OWNER_ID)
        )
        assert "Статус обновлён" in [text for _, text in calls] or any(
            text == "Статус обновлён" for _, text in calls
        )
        async with session_factory() as session:
            barber = await BarberRepository(session, tenant_id).get(barber_id)
        assert barber.is_active is True
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_barber_reactivation_at_limit_fails(session_factory, dispatcher):
    tenant_id, bot_id, branch_id = await _make_tenant(session_factory)
    await _add_barber(session_factory, tenant_id, branch_id, name="Active1", is_active=True)
    await _add_barber(session_factory, tenant_id, branch_id, name="Active2", is_active=True)
    inactive_id = await _add_barber(session_factory, tenant_id, branch_id, name="Inactive", is_active=False)
    try:
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback(f"ad:brb_toggle:{inactive_id}", OWNER_ID)
        )
        # Пункт 6: понятное билинговое сообщение, а не крах/сырое исключение.
        assert "Достигнут лимит тарифа" in texts(calls)
        assert "Барберы" in texts(calls)
        async with session_factory() as session:
            barber = await BarberRepository(session, tenant_id).get(inactive_id)
        assert barber.is_active is False
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_barber_reactivation_unlimited_on_pro_plan_succeeds(session_factory, dispatcher):
    tenant_id, bot_id, branch_id = await _make_tenant(session_factory)
    await _set_plan(session_factory, tenant_id, plan_code="pro")
    await _add_barber(session_factory, tenant_id, branch_id, name="Active1", is_active=True)
    await _add_barber(session_factory, tenant_id, branch_id, name="Active2", is_active=True)
    await _add_barber(session_factory, tenant_id, branch_id, name="Active3", is_active=True)
    inactive_id = await _add_barber(session_factory, tenant_id, branch_id, name="Inactive", is_active=False)
    try:
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback(f"ad:brb_toggle:{inactive_id}", OWNER_ID)
        )
        assert "Достигнут лимит" not in texts(calls)
        async with session_factory() as session:
            barber = await BarberRepository(session, tenant_id).get(inactive_id)
        assert barber.is_active is True
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_barber_reactivation_limit_is_tenant_isolated(session_factory, dispatcher):
    """Пункт 4: арендатор A на пределе лимита не влияет на арендатора B."""
    tenant_a, bot_a, branch_a = await _make_tenant(session_factory)
    tenant_b, bot_b, branch_b = await _make_tenant(session_factory)
    await _add_barber(session_factory, tenant_a, branch_a, name="A1", is_active=True)
    await _add_barber(session_factory, tenant_a, branch_a, name="A2", is_active=True)
    inactive_a = await _add_barber(session_factory, tenant_a, branch_a, name="A-inactive", is_active=False)
    inactive_b = await _add_barber(session_factory, tenant_b, branch_b, name="B-inactive", is_active=False)
    try:
        calls_a = await feed(
            dispatcher, _bot(bot_a), make_callback(f"ad:brb_toggle:{inactive_a}", OWNER_ID)
        )
        assert "Достигнут лимит тарифа" in texts(calls_a)

        calls_b = await feed(
            dispatcher, _bot(bot_b), make_callback(f"ad:brb_toggle:{inactive_b}", OWNER_ID)
        )
        assert "Достигнут лимит" not in texts(calls_b)
        async with session_factory() as session:
            barber_b = await BarberRepository(session, tenant_b).get(inactive_b)
        assert barber_b.is_active is True
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


# === Услуги (MAX_SERVICES = 10 на Free) =====================================
async def test_service_reactivation_under_limit_succeeds(session_factory, dispatcher):
    tenant_id, bot_id, _branch_id = await _make_tenant(session_factory)
    service_id = await _add_service(session_factory, tenant_id, name="Solo", is_active=False)
    try:
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback(f"ad:svc_toggle:{service_id}", OWNER_ID)
        )
        assert any(text == "Статус обновлён" for _, text in calls)
        async with session_factory() as session:
            service = await ServiceRepository(session, tenant_id).get(service_id)
        assert service.is_active is True
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_service_reactivation_at_limit_fails(session_factory, dispatcher):
    tenant_id, bot_id, _branch_id = await _make_tenant(session_factory)
    for index in range(10):
        await _add_service(session_factory, tenant_id, name=f"Active-{index}", is_active=True)
    inactive_id = await _add_service(session_factory, tenant_id, name="Inactive", is_active=False)
    try:
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback(f"ad:svc_toggle:{inactive_id}", OWNER_ID)
        )
        assert "Достигнут лимит тарифа" in texts(calls)
        assert "Услуги" in texts(calls)
        async with session_factory() as session:
            service = await ServiceRepository(session, tenant_id).get(inactive_id)
        assert service.is_active is False
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_service_reactivation_unlimited_on_pro_plan_succeeds(session_factory, dispatcher):
    tenant_id, bot_id, _branch_id = await _make_tenant(session_factory)
    await _set_plan(session_factory, tenant_id, plan_code="pro")
    for index in range(10):
        await _add_service(session_factory, tenant_id, name=f"Active-{index}", is_active=True)
    inactive_id = await _add_service(session_factory, tenant_id, name="Inactive", is_active=False)
    try:
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback(f"ad:svc_toggle:{inactive_id}", OWNER_ID)
        )
        assert "Достигнут лимит" not in texts(calls)
        async with session_factory() as session:
            service = await ServiceRepository(session, tenant_id).get(inactive_id)
        assert service.is_active is True
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_service_reactivation_limit_is_tenant_isolated(session_factory, dispatcher):
    tenant_a, bot_a, _branch_a = await _make_tenant(session_factory)
    tenant_b, bot_b, _branch_b = await _make_tenant(session_factory)
    for index in range(10):
        await _add_service(session_factory, tenant_a, name=f"A-{index}", is_active=True)
    inactive_a = await _add_service(session_factory, tenant_a, name="A-inactive", is_active=False)
    inactive_b = await _add_service(session_factory, tenant_b, name="B-inactive", is_active=False)
    try:
        calls_a = await feed(
            dispatcher, _bot(bot_a), make_callback(f"ad:svc_toggle:{inactive_a}", OWNER_ID)
        )
        assert "Достигнут лимит тарифа" in texts(calls_a)

        calls_b = await feed(
            dispatcher, _bot(bot_b), make_callback(f"ad:svc_toggle:{inactive_b}", OWNER_ID)
        )
        assert "Достигнут лимит" not in texts(calls_b)
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


# === Не связанная с реактивацией регрессия: деактивация без ограничений ====
async def test_deactivation_never_requires_limit_check(session_factory, dispatcher):
    """Скрытие (is_active=True -> False) не должно требовать проверки
    лимита ни для барбера, ни для услуги — лимит проверяется только на
    активацию."""
    tenant_id, bot_id, branch_id = await _make_tenant(session_factory)
    barber_id = await _add_barber(session_factory, tenant_id, branch_id, name="ToHide", is_active=True)
    service_id = await _add_service(session_factory, tenant_id, name="ToHide", is_active=True)
    try:
        calls_barber = await feed(
            dispatcher, _bot(bot_id), make_callback(f"ad:brb_toggle:{barber_id}", OWNER_ID)
        )
        assert any(text == "Статус обновлён" for _, text in calls_barber)
        calls_service = await feed(
            dispatcher, _bot(bot_id), make_callback(f"ad:svc_toggle:{service_id}", OWNER_ID)
        )
        assert any(text == "Статус обновлён" for _, text in calls_service)
    finally:
        await _delete_tenant(session_factory, tenant_id)
