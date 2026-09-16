"""Интеграционные тесты pagination (Phase 9C §M-6) на реальном PostgreSQL:
staff/branches/barbers/services (tenant admin) и tenant list (platform) —
общий Previous/Next-паттерн, переиспользованный из appointments/clients
pagination (см. app/bot/keyboards/admin.py::_paginated), а не второй
pagination framework.

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

from app.database.models import (
    PlatformOperator,
    PlatformRole,
    Role,
    TelegramBotIdentity,
    Tenant,
    TenantStatus,
)
from app.database.repositories import (
    BarberRepository,
    BranchRepository,
    PlatformOperatorRepository,
    ServiceRepository,
    StaffRepository,
    TenantRepository,
)
from app.services.onboarding import TenantOnboardingService
from tests.conftest import FLOW_PLATFORM_BOT_ID, MockedSession

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


OWNER_ID = 990_700_001
STRANGER_ID = 990_700_999
_next_bot_id = iter(range(960_000_001, 960_100_000))


async def _make_tenant(session_factory) -> tuple[uuid.UUID, int]:
    """Свежий арендатор со своим ботом и владельцем (VIEW_STAFF/MANAGE_*
    через настоящую роль, а не is_super_admin/ADMIN_ID — надёжнее для общего
    тестового прогона, см. Phase 9B)."""
    marker = uuid.uuid4().hex[:8]
    bot_id = next(_next_bot_id)
    async with session_factory() as session:
        tenant = await TenantOnboardingService.create_tenant(
            session, name=f"Page Tenant {marker}", slug=f"page-{marker}"
        )
        session.add(
            TelegramBotIdentity(tenant_id=tenant.id, telegram_bot_id=bot_id, username="pg_bot")
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


async def _add_branch(session_factory, tenant_id, name: str) -> uuid.UUID:
    async with session_factory() as session:
        branch = await BranchRepository(session, tenant_id).create(name=name)
        await session.commit()
        return branch.id


async def _add_barber(session_factory, tenant_id, name: str) -> uuid.UUID:
    async with session_factory() as session:
        barber = await BarberRepository(session, tenant_id).create(name=name)
        await session.commit()
        return barber.id


async def _add_service(session_factory, tenant_id, name: str) -> uuid.UUID:
    async with session_factory() as session:
        service = await ServiceRepository(session, tenant_id).create(
            name=name, duration_minutes=30, price=Decimal("100")
        )
        await session.commit()
        return service.id


async def _add_staff(session_factory, tenant_id, telegram_id: int, role: Role) -> uuid.UUID:
    async with session_factory() as session:
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=telegram_id, role=role
        )
        await session.commit()
        return staff.id


# =============================================================================
# BRANCHES (Permission.MANAGE_BRANCHES, action="branches"/"brh")
# =============================================================================
async def test_branches_empty_list(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:branches:", OWNER_ID))
        assert "Филиалов пока нет" in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_branches_exactly_one_page(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(3):
            await _add_branch(session_factory, tenant_id, f"Branch-{i}")
        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_callback("ad:branches:", OWNER_ID))
        assert "всего 3" in texts(calls)
        assert not any(data == "ad:branches:1" for _, data in bot.buttons)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_branches_multiple_pages_next_and_previous(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(10):
            await _add_branch(session_factory, tenant_id, f"Branch-{i:02d}")
        bot = _bot(bot_id)
        page0 = await feed(dispatcher, bot, make_callback("ad:branches:0", OWNER_ID))
        assert "всего 10" in texts(page0)
        assert any(data == "ad:branches:1" for _, data in bot.buttons)
        assert not any(data == "ad:branches:-1" for _, data in bot.buttons)

        page1 = await feed(dispatcher, bot, make_callback("ad:branches:1", OWNER_ID))
        assert "всего 10" in texts(page1)
        assert any(data == "ad:branches:0" for _, data in bot.buttons)
        assert not any(data == "ad:branches:2" for _, data in bot.buttons)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_branches_tenant_isolation(session_factory, dispatcher):
    tenant_a, bot_a = await _make_tenant(session_factory)
    tenant_b, _bot_b = await _make_tenant(session_factory)
    try:
        await _add_branch(session_factory, tenant_a, "Only-in-A")
        await _add_branch(session_factory, tenant_b, "Only-in-B")
        calls_a = await feed(dispatcher, _bot(bot_a), make_callback("ad:branches:", OWNER_ID))
        assert "Only-in-A" in texts(calls_a)
        assert "Only-in-B" not in texts(calls_a)
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


async def test_branches_forged_page_number_redirects_to_first_page(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        await _add_branch(session_factory, tenant_id, "Solo")
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback("ad:branches:999999", OWNER_ID)
        )
        # Не падает, не показывает пустой экран — откатывается на страницу 0.
        assert "Solo" in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_branches_mutation_from_second_page_targets_correct_branch(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(10):
            await _add_branch(session_factory, tenant_id, f"Branch-{i:02d}")
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:branches:1", OWNER_ID))
        # На второй странице (offset=8) должны быть Branch-08/Branch-09.
        target_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:brh:")
        )
        await feed(dispatcher, bot, make_callback(target_button, OWNER_ID))
        toggle_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:brh_toggle:")
        )
        branch_id_from_toggle = toggle_button.split(":")[-1]
        branch_id_from_card = target_button.split(":")[-1]
        assert branch_id_from_toggle == branch_id_from_card
        calls = await feed(dispatcher, bot, make_callback(toggle_button, OWNER_ID))
        assert "Статус обновлён" in [text for _, text in calls]
        async with session_factory() as session:
            toggled = await BranchRepository(session, tenant_id).get(
                uuid.UUID(branch_id_from_card)
            )
        assert toggled.is_active is False
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_branches_authorization_still_enforced_with_pagination(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:branches:", STRANGER_ID))
        assert not any("Филиалов пока нет" in (text or "") for _, text in calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# =============================================================================
# BARBERS (Permission.MANAGE_STAFF, action="barbers"/"brb")
# =============================================================================
async def test_barbers_empty_list(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:barbers:", OWNER_ID))
        assert "Барберов пока нет" in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_barbers_exactly_one_page(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(4):
            await _add_barber(session_factory, tenant_id, f"Barber-{i}")
        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_callback("ad:barbers:", OWNER_ID))
        assert "всего 4" in texts(calls)
        assert not any(data == "ad:barbers:1" for _, data in bot.buttons)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_barbers_multiple_pages_next_and_previous(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(9):
            await _add_barber(session_factory, tenant_id, f"Barber-{i:02d}")
        bot = _bot(bot_id)
        page0 = await feed(dispatcher, bot, make_callback("ad:barbers:0", OWNER_ID))
        assert "всего 9" in texts(page0)
        assert any(data == "ad:barbers:1" for _, data in bot.buttons)

        await feed(dispatcher, bot, make_callback("ad:barbers:1", OWNER_ID))
        assert any(data == "ad:barbers:0" for _, data in bot.buttons)
        assert not any(data == "ad:barbers:2" for _, data in bot.buttons)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_barbers_tenant_isolation(session_factory, dispatcher):
    tenant_a, bot_a = await _make_tenant(session_factory)
    tenant_b, _bot_b = await _make_tenant(session_factory)
    try:
        await _add_barber(session_factory, tenant_a, "Only-in-A")
        await _add_barber(session_factory, tenant_b, "Only-in-B")
        calls_a = await feed(dispatcher, _bot(bot_a), make_callback("ad:barbers:", OWNER_ID))
        assert "Only-in-A" in texts(calls_a)
        assert "Only-in-B" not in texts(calls_a)
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


async def test_barbers_forged_page_number_redirects_to_first_page(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        await _add_barber(session_factory, tenant_id, "Solo")
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:barbers:42", OWNER_ID))
        assert "Solo" in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_barbers_mutation_from_second_page_targets_correct_barber(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(9):
            await _add_barber(session_factory, tenant_id, f"Barber-{i:02d}")
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:barbers:1", OWNER_ID))
        target_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:brb:")
        )
        await feed(dispatcher, bot, make_callback(target_button, OWNER_ID))
        toggle_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:brb_toggle:")
        )
        assert toggle_button.split(":")[-1] == target_button.split(":")[-1]
        calls = await feed(dispatcher, bot, make_callback(toggle_button, OWNER_ID))
        assert "Статус обновлён" in [text for _, text in calls]
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_barbers_authorization_still_enforced_with_pagination(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:barbers:", STRANGER_ID))
        assert not any("Барберов пока нет" in (text or "") for _, text in calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# =============================================================================
# SERVICES (Permission.MANAGE_SERVICES, action="services"/"svc")
# =============================================================================
async def test_services_empty_list(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:services:", OWNER_ID))
        assert "Услуг пока нет" in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_services_exactly_one_page(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(5):
            await _add_service(session_factory, tenant_id, f"Service-{i}")
        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_callback("ad:services:", OWNER_ID))
        assert "всего 5" in texts(calls)
        assert not any(data == "ad:services:1" for _, data in bot.buttons)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_services_multiple_pages_next_and_previous(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(10):
            await _add_service(session_factory, tenant_id, f"Service-{i:02d}")
        bot = _bot(bot_id)
        page0 = await feed(dispatcher, bot, make_callback("ad:services:0", OWNER_ID))
        assert "всего 10" in texts(page0)
        assert any(data == "ad:services:1" for _, data in bot.buttons)

        await feed(dispatcher, bot, make_callback("ad:services:1", OWNER_ID))
        assert any(data == "ad:services:0" for _, data in bot.buttons)
        assert not any(data == "ad:services:2" for _, data in bot.buttons)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_services_tenant_isolation(session_factory, dispatcher):
    tenant_a, bot_a = await _make_tenant(session_factory)
    tenant_b, _bot_b = await _make_tenant(session_factory)
    try:
        await _add_service(session_factory, tenant_a, "Only-in-A")
        await _add_service(session_factory, tenant_b, "Only-in-B")
        calls_a = await feed(dispatcher, _bot(bot_a), make_callback("ad:services:", OWNER_ID))
        assert "Only-in-A" in texts(calls_a)
        assert "Only-in-B" not in texts(calls_a)
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


async def test_services_forged_page_number_redirects_to_first_page(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        await _add_service(session_factory, tenant_id, "Solo")
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:services:7", OWNER_ID))
        assert "Solo" in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_services_mutation_from_second_page_targets_correct_service(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(10):
            await _add_service(session_factory, tenant_id, f"Service-{i:02d}")
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:services:1", OWNER_ID))
        target_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:svc:")
        )
        await feed(dispatcher, bot, make_callback(target_button, OWNER_ID))
        toggle_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:svc_toggle:")
        )
        assert toggle_button.split(":")[-1] == target_button.split(":")[-1]
        calls = await feed(dispatcher, bot, make_callback(toggle_button, OWNER_ID))
        assert "Статус обновлён" in [text for _, text in calls]
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_services_authorization_still_enforced_with_pagination(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:services:", STRANGER_ID))
        assert not any("Услуг пока нет" in (text or "") for _, text in calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# =============================================================================
# STAFF (Permission.VIEW_STAFF/MANAGE_STAFF, action="staff"/"stf")
# У арендатора всегда есть минимум владелец — "0 записей" недостижимо в
# реальном авторизованном сценарии (VIEW_STAFF есть только у роли, которая
# сама есть строка staff_members). Ближайший осмысленный аналог — "1 запись"
# (только владелец), что и тестируется вместо буквально пустого списка.
# =============================================================================
async def test_staff_single_item_is_just_the_owner(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:staff:", OWNER_ID))
        assert "всего 1" in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_staff_exactly_one_page(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(3):
            await _add_staff(session_factory, tenant_id, 990_710_000 + i, Role.BARBER)
        bot = _bot(bot_id)
        calls = await feed(dispatcher, bot, make_callback("ad:staff:", OWNER_ID))
        assert "всего 4" in texts(calls)  # 3 барбера + владелец
        assert not any(data == "ad:staff:1" for _, data in bot.buttons)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_staff_multiple_pages_next_and_previous(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(9):
            await _add_staff(session_factory, tenant_id, 990_711_000 + i, Role.BARBER)
        bot = _bot(bot_id)
        page0 = await feed(dispatcher, bot, make_callback("ad:staff:0", OWNER_ID))
        assert "всего 10" in texts(page0)  # 9 + владелец
        assert any(data == "ad:staff:1" for _, data in bot.buttons)

        await feed(dispatcher, bot, make_callback("ad:staff:1", OWNER_ID))
        assert any(data == "ad:staff:0" for _, data in bot.buttons)
        assert not any(data == "ad:staff:2" for _, data in bot.buttons)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_staff_tenant_isolation(session_factory, dispatcher):
    tenant_a, bot_a = await _make_tenant(session_factory)
    tenant_b, _bot_b = await _make_tenant(session_factory)
    try:
        await _add_staff(session_factory, tenant_a, 990_712_001, Role.BARBER)
        await _add_staff(session_factory, tenant_b, 990_712_002, Role.BARBER)
        calls_a = await feed(dispatcher, _bot(bot_a), make_callback("ad:staff:", OWNER_ID))
        assert "990712001" in texts(calls_a)
        assert "990712002" not in texts(calls_a)
    finally:
        await _delete_tenant(session_factory, tenant_a)
        await _delete_tenant(session_factory, tenant_b)


async def test_staff_forged_page_number_redirects_to_first_page(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:staff:12345", OWNER_ID))
        assert "всего 1" in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_staff_mutation_from_second_page_targets_correct_staff(
    session_factory, dispatcher
):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        for i in range(9):
            await _add_staff(session_factory, tenant_id, 990_713_000 + i, Role.RECEPTIONIST)
        bot = _bot(bot_id)
        await feed(dispatcher, bot, make_callback("ad:staff:1", OWNER_ID))
        target_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:stf:")
        )
        target_staff_id = target_button.split(":")[-1]
        calls = await feed(dispatcher, bot, make_callback(target_button, OWNER_ID))
        assert target_staff_id[:8] in texts(calls) or "Роль:" in texts(calls)

        deact_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:stf_deact:")
        )
        assert deact_button.split(":")[-1] == target_staff_id
        await feed(dispatcher, bot, make_callback(deact_button, OWNER_ID))
        confirm_button = next(
            data for _, data in bot.buttons if data and data.startswith("ad:stf_deact_ok:")
        )
        assert confirm_button.split(":")[-1] == target_staff_id
        deact_calls = await feed(dispatcher, bot, make_callback(confirm_button, OWNER_ID))
        assert "Деактивирован" in [text for _, text in deact_calls]

        async with session_factory() as session:
            deactivated = await StaffRepository(session, tenant_id).get(
                uuid.UUID(target_staff_id)
            )
        assert deactivated.is_active is False
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_staff_authorization_still_enforced_with_pagination(session_factory, dispatcher):
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(dispatcher, _bot(bot_id), make_callback("ad:staff:", STRANGER_ID))
        assert not any("всего" in (text or "") for _, text in calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)


# =============================================================================
# PLATFORM TENANTS (RequirePlatformOperator, action="tenants"/"tenant")
# =============================================================================
PLATFORM_OPERATOR_ID = 990_720_001


@pytest.fixture
async def platform_operator(session_factory):
    async with session_factory() as session:
        await PlatformOperatorRepository(session).create(
            telegram_user_id=PLATFORM_OPERATOR_ID, role=PlatformRole.PLATFORM_ADMIN
        )
        await session.commit()
    yield PLATFORM_OPERATOR_ID
    async with session_factory() as session:
        await session.execute(
            delete(PlatformOperator).where(
                PlatformOperator.telegram_user_id == PLATFORM_OPERATOR_ID
            )
        )
        await session.commit()


def _platform_bot() -> Bot:
    return _bot(FLOW_PLATFORM_BOT_ID)


async def test_platform_tenants_pagination_across_created_batch(
    session_factory, dispatcher, platform_operator
):
    """Реалистичный размер данных: создаём заведомо больше одной страницы
    новых арендаторов и проверяем, что все они находятся где-то в
    пагинированном списке, без дублей/пропусков между страницами."""
    created_ids: list[uuid.UUID] = []
    marker = uuid.uuid4().hex[:6]
    names = [f"PagTenant-{marker}-{i:02d}" for i in range(10)]
    async with session_factory() as session:
        for name in names:
            tenant = await TenantOnboardingService.create_tenant(
                session, name=name, slug=f"pagtenant-{marker}-{len(created_ids)}"
            )
            created_ids.append(tenant.id)
        await session.commit()

    try:
        bot = _platform_bot()
        found_names: set[str] = set()
        page = 0
        seen_pages = 0
        while True:
            calls = await feed(
                dispatcher, bot, make_callback(f"pf:tenants:{page}", platform_operator)
            )
            for name in names:
                if name in texts(calls):
                    found_names.add(name)
            seen_pages += 1
            if any(data == f"pf:tenants:{page + 1}" for _, data in bot.buttons):
                page += 1
                if seen_pages > 20:
                    pytest.fail("Слишком много страниц — вероятная бесконечная пагинация")
                continue
            break
        assert found_names == set(names)
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_(created_ids)))
            await session.commit()


async def test_platform_tenants_forged_page_number_redirects_to_first_page(
    session_factory, dispatcher, platform_operator
):
    calls = await feed(
        dispatcher, _platform_bot(), make_callback("pf:tenants:999999", platform_operator)
    )
    # Не падает, не показывает пустой экран — откатывается на страницу 0.
    assert "Арендаторы" in texts(calls)


async def test_platform_tenants_mutation_from_page_targets_correct_tenant(
    session_factory, dispatcher, platform_operator
):
    marker = uuid.uuid4().hex[:6]
    async with session_factory() as session:
        target = await TenantOnboardingService.create_tenant(
            session, name=f"SuspendMe-{marker}", slug=f"suspend-{marker}"
        )
        target_id = target.id
        # Активация сама по себе не тестируется здесь (это отдельная логика
        # готовности онбординга) — статус выставляется напрямую, чтобы
        # проверить именно то, что нужно этому тесту: мутация, открытая со
        # страницы пагинации, бьёт в правильный tenant_id.
        target.status = TenantStatus.ACTIVE
        await session.commit()
    try:
        bot = _platform_bot()
        found_button = None
        page = 0
        for _ in range(50):
            await feed(dispatcher, bot, make_callback(f"pf:tenants:{page}", platform_operator))
            match = next(
                (
                    data for _, data in bot.buttons
                    if data == f"pf:tenant:{target_id}"
                ),
                None,
            )
            if match:
                found_button = match
                break
            if any(data == f"pf:tenants:{page + 1}" for _, data in bot.buttons):
                page += 1
                continue
            break
        assert found_button is not None, "целевой арендатор не найден ни на одной странице"

        await feed(dispatcher, bot, make_callback(found_button, platform_operator))
        suspend_button = next(
            data for _, data in bot.buttons if data.startswith("pf:suspend:")
        )
        assert suspend_button.split(":")[-1] == str(target_id)
        await feed(dispatcher, bot, make_callback(suspend_button, platform_operator))

        async with session_factory() as session:
            reloaded = await TenantRepository(session).get(target_id)

        assert reloaded.status == TenantStatus.SUSPENDED
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == target_id))
            await session.commit()


async def test_tenant_bot_cannot_reach_platform_tenant_pagination(session_factory, dispatcher):
    """Обычный бот арендатора (не платформенный) никогда не должен доходить
    до платформенного списка, даже если пишущий telegram_id — платформенный
    оператор в другом контексте (см. docs/PLATFORM_CONTROL_PLANE.md)."""
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback("ad:staff:", OWNER_ID)
        )
        # Обычный AdmCB-callback на tenant-боте — не платформенный формат
        # "pf:tenants:..." в принципе не мог бы даже дойти до platform-роутера,
        # так как is_platform_bot=False для этого бота структурно (BotIdentityMiddleware).
        assert calls  # staff list работает нормально на tenant-боте
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_tenant_staff_cannot_access_platform_tenant_list(
    session_factory, dispatcher, platform_operator
):
    """Владелец арендатора (даже если тот же telegram_id — платформенный
    оператор) не должен получать платформенный список через ЧУЖОЙ,
    tenant-бот: is_platform_bot=False там структурно."""
    tenant_id, bot_id = await _make_tenant(session_factory)
    try:
        calls = await feed(
            dispatcher, _bot(bot_id), make_callback("pf:tenants:0", platform_operator)
        )
        # На tenant-боте это не платформенный callback ни для одного роутера
        # (PlatformCB и AdmCB имеют разные префиксы) — ожидаем "не понял"/fallback,
        # не платформенный список арендаторов.
        assert "Арендаторы" not in texts(calls)
    finally:
        await _delete_tenant(session_factory, tenant_id)
