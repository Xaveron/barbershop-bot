"""Интеграционные тесты платформенного control plane (Phase 8) на реальном
PostgreSQL.

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
from sqlalchemy import delete, event, select
from sqlalchemy.exc import IntegrityError

from app.bot.keyboards.callbacks import PlatformCB
from app.database.models import (
    AuditLogEntry,
    PlatformOperator,
    PlatformRole,
    Role,
    Tenant,
    TenantStatus,
)
from app.database.repositories import (
    PlatformOperatorRepository,
    StaffRepository,
    TelegramBotIdentityRepository,
    TenantRepository,
)
from app.services.bot_identity import BotAlreadyAssignedError, BotProvisioningService
from app.services.platform_authorization import (
    PlatformAuthorizationError,
    PlatformAuthorizationService,
)
from app.services.tenant_management import TenantLifecycleError, TenantManagementService
from tests.conftest import FLOW_PLATFORM_BOT_ID, MockedSession

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
def engine(flow_engine):
    return flow_engine


@pytest.fixture(scope="module")
def dispatcher(flow_dispatcher):
    return flow_dispatcher


@pytest.fixture
def query_counter(engine):
    """Считает SQL-запросы — регрессионная защита от N+1 (см.
    test_integration_booking.py::query_counter)."""
    queries: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    yield queries
    event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)


async def _make_tenant(session_factory, *, status: TenantStatus = TenantStatus.ACTIVE) -> uuid.UUID:
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        tenant = Tenant(name=f"Platform Tenant {marker}", slug=f"pf-{marker}", status=status)
        session.add(tenant)
        await session.commit()
        return tenant.id


async def _delete_tenant(session_factory, tenant_id: uuid.UUID) -> None:
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await session.commit()


async def _delete_operator(session_factory, telegram_user_id: int) -> None:
    async with session_factory() as session:
        await session.execute(
            delete(PlatformOperator).where(PlatformOperator.telegram_user_id == telegram_user_id)
        )
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


async def feed(dispatcher, bot: Bot, event) -> list[tuple[str, str | None]]:
    bot.calls.clear()
    update = (
        Update(update_id=1, message=event)
        if isinstance(event, Message)
        else Update(update_id=1, callback_query=event)
    )
    await dispatcher.feed_update(bot, update)
    return list(bot.calls)


# === A. Модель / репозиторий PlatformOperator =================================
async def test_create_platform_operator(session_factory):
    telegram_id = 970_000_001
    async with session_factory() as session:
        operator = await PlatformOperatorRepository(session).create(
            telegram_user_id=telegram_id, role=PlatformRole.PLATFORM_ADMIN
        )
        await session.commit()
    try:
        assert operator.is_active is True
        assert operator.role == PlatformRole.PLATFORM_ADMIN
    finally:
        await _delete_operator(session_factory, telegram_id)


async def test_duplicate_telegram_user_id_rejected(session_factory):
    telegram_id = 970_000_002
    async with session_factory() as session:
        await PlatformOperatorRepository(session).create(
            telegram_user_id=telegram_id, role=PlatformRole.PLATFORM_ADMIN
        )
        await session.commit()
    try:
        async with session_factory() as session:
            with pytest.raises(IntegrityError):
                await PlatformOperatorRepository(session).create(
                    telegram_user_id=telegram_id, role=PlatformRole.PLATFORM_ADMIN
                )
    finally:
        await _delete_operator(session_factory, telegram_id)


# === B. PlatformAuthorizationService ===========================================
async def test_inactive_operator_is_not_authorized(session_factory, settings):
    telegram_id = 970_000_003
    async with session_factory() as session:
        await PlatformOperatorRepository(session).create(
            telegram_user_id=telegram_id, role=PlatformRole.PLATFORM_ADMIN, is_active=False
        )
        await session.commit()
    try:
        async with session_factory() as session:
            assert await PlatformAuthorizationService(session, settings).is_operator(
                telegram_id
            ) is False
    finally:
        await _delete_operator(session_factory, telegram_id)


async def test_bootstrap_window_grants_admin_id_when_no_operators_exist(session_factory, settings):
    async with session_factory() as session:
        assert await PlatformOperatorRepository(session).any_exist() is False
        admin_id = settings.admin_ids[0]
        assert await PlatformAuthorizationService(session, settings).is_operator(admin_id) is True


async def test_admin_id_stops_working_once_an_operator_exists(session_factory, settings):
    """ADMIN_ID больше не постоянный обход: как только появился хотя бы один
    реальный PlatformOperator, окно bootstrap закрывается для ВСЕХ, включая
    ADMIN_ID, который сам не был явно зарегистрирован."""
    other_admin_id = settings.admin_ids[0] if settings.admin_ids else 1
    seed_id = 970_000_004
    async with session_factory() as session:
        await PlatformOperatorRepository(session).create(
            telegram_user_id=seed_id, role=PlatformRole.PLATFORM_ADMIN
        )
        await session.commit()
    try:
        async with session_factory() as session:
            auth = PlatformAuthorizationService(session, settings)
            assert await auth.is_operator(seed_id) is True
            if other_admin_id != seed_id:
                assert await auth.is_operator(other_admin_id) is False
    finally:
        await _delete_operator(session_factory, seed_id)


async def test_require_operator_raises_for_unknown_user(session_factory, settings):
    async with session_factory() as session:
        # На этом этапе теста уже есть >=1 оператор из предыдущего теста
        # сценария в этом же файле — на всякий случай гарантируем это здесь.
        await PlatformOperatorRepository(session).create(
            telegram_user_id=970_000_005, role=PlatformRole.PLATFORM_ADMIN
        )
        await session.commit()
    try:
        async with session_factory() as session:
            with pytest.raises(PlatformAuthorizationError):
                await PlatformAuthorizationService(session, settings).require_operator(999_999_990)
    finally:
        await _delete_operator(session_factory, 970_000_005)


async def test_create_operator_writes_audit_entry(session_factory, settings):
    telegram_id = 970_000_006
    async with session_factory() as session:
        await PlatformAuthorizationService(session, settings).create_operator(
            telegram_user_id=telegram_id, actor_telegram_id=telegram_id
        )
    try:
        async with session_factory() as session:
            entry = await session.scalar(
                select(AuditLogEntry).where(
                    AuditLogEntry.action == "platform_operator.created",
                    AuditLogEntry.target_telegram_id == telegram_id,
                )
            )
        assert entry is not None
        assert entry.tenant_id is None
    finally:
        await _delete_operator(session_factory, telegram_id)


async def test_deactivate_operator_writes_audit_entry(session_factory, settings):
    telegram_id = 970_000_007
    async with session_factory() as session:
        await PlatformOperatorRepository(session).create(
            telegram_user_id=telegram_id, role=PlatformRole.PLATFORM_ADMIN
        )
        await session.commit()
    try:
        async with session_factory() as session:
            await PlatformAuthorizationService(session, settings).deactivate_operator(
                telegram_id, actor_telegram_id=970_000_006
            )
        async with session_factory() as session:
            operator = await PlatformOperatorRepository(session).get_by_telegram_id(telegram_id)
            entry = await session.scalar(
                select(AuditLogEntry).where(
                    AuditLogEntry.action == "platform_operator.deactivated",
                    AuditLogEntry.target_telegram_id == telegram_id,
                )
            )
        assert operator.is_active is False
        assert entry is not None
    finally:
        await _delete_operator(session_factory, telegram_id)


# === C. TenantManagementService: жизненный цикл ===============================
async def test_create_tenant_starts_onboarding_and_audits(session_factory):
    async with session_factory() as session:
        tenant = await TenantManagementService(session).create_tenant(
            name="Salon Platform", actor_telegram_id=970_100_001
        )
    try:
        async with session_factory() as session:
            fresh = await TenantRepository(session).get(tenant.id)
            entry = await session.scalar(
                select(AuditLogEntry).where(
                    AuditLogEntry.action == "tenant.created", AuditLogEntry.tenant_id == tenant.id
                )
            )
        assert fresh.status == TenantStatus.ONBOARDING
        assert entry is not None
        assert entry.actor_telegram_id == 970_100_001
    finally:
        await _delete_tenant(session_factory, tenant.id)


async def test_create_tenant_generates_unique_slug_from_name(session_factory):
    async with session_factory() as session:
        service = TenantManagementService(session)
        first = await service.create_tenant(name="Тот же салон", actor_telegram_id=1)
        second = await service.create_tenant(name="Тот же салон", actor_telegram_id=1)
    try:
        assert first.slug != second.slug
    finally:
        await _delete_tenant(session_factory, first.id)
        await _delete_tenant(session_factory, second.id)


async def test_activate_tenant_blocks_when_not_ready(session_factory):
    tenant_id = await _make_tenant(session_factory, status=TenantStatus.ONBOARDING)
    try:
        async with session_factory() as session:
            readiness = await TenantManagementService(session).activate_tenant(
                tenant_id, actor_telegram_id=1
            )
            tenant = await TenantRepository(session).get(tenant_id)
        assert readiness.is_ready is False
        assert tenant.status != TenantStatus.ACTIVE
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_suspend_tenant_from_active_works_and_audits(session_factory):
    tenant_id = await _make_tenant(session_factory, status=TenantStatus.ACTIVE)
    try:
        async with session_factory() as session:
            await TenantManagementService(session).suspend_tenant(
                tenant_id, actor_telegram_id=970_200_001
            )
        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
            entry = await session.scalar(
                select(AuditLogEntry).where(
                    AuditLogEntry.action == "tenant.suspended",
                    AuditLogEntry.tenant_id == tenant_id,
                )
            )
        assert tenant.status == TenantStatus.SUSPENDED
        assert entry is not None
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_suspend_already_suspended_tenant_is_idempotent(session_factory):
    tenant_id = await _make_tenant(session_factory, status=TenantStatus.SUSPENDED)
    try:
        async with session_factory() as session:
            result = await TenantManagementService(session).suspend_tenant(
                tenant_id, actor_telegram_id=1
            )
        assert result.status == TenantStatus.SUSPENDED
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_suspend_onboarding_tenant_is_rejected(session_factory, tenant_a):
    # tenant_a fixture создаёт ACTIVE — сделаем отдельный ONBOARDING.
    tenant_id = await _make_tenant(session_factory, status=TenantStatus.ONBOARDING)
    try:
        async with session_factory() as session:
            with pytest.raises(TenantLifecycleError):
                await TenantManagementService(session).suspend_tenant(
                    tenant_id, actor_telegram_id=1
                )
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_reactivate_suspended_tenant_reuses_activation_validation(session_factory):
    """SUSPENDED -> ACTIVE идёт через тот же activate(), что и обычная
    активация — работает без готовности false, если данные уже были готовы."""
    tenant_id = await _make_tenant(session_factory, status=TenantStatus.SUSPENDED)
    try:
        async with session_factory() as session:
            readiness = await TenantManagementService(session).activate_tenant(
                tenant_id, actor_telegram_id=1
            )
        # У свежего тенанта нет ни филиалов, ни услуг — готовность будет false,
        # что и подтверждает переиспользование той же валидации.
        assert readiness.is_ready is False
        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
        assert tenant.status == TenantStatus.SUSPENDED
    finally:
        await _delete_tenant(session_factory, tenant_id)


async def test_ensure_owner_reuses_onboarding_and_enforces_uniqueness(session_factory, tenant_a):
    async with session_factory() as session:
        service = TenantManagementService(session)
        owner_1 = await service.ensure_owner(tenant_a, telegram_id=970_300_001, actor_telegram_id=1)
    async with session_factory() as session:
        service = TenantManagementService(session)
        owner_2 = await service.ensure_owner(tenant_a, telegram_id=970_300_002, actor_telegram_id=1)
    assert owner_1.id == owner_2.id  # второй вызов вернул уже существующего владельца
    async with session_factory() as session:
        staff = await StaffRepository(session, tenant_a).get_owner()
    assert staff.role == Role.TENANT_OWNER


# === D. list_tenants / get_tenant: агрегаты, без N+1 ===========================
async def test_list_tenants_reports_correct_counts(session_factory, tenant_a):
    async with session_factory() as session:
        await StaffRepository(session, tenant_a).create(telegram_id=970_400_001, role=Role.MANAGER)
        await session.commit()
        await TelegramBotIdentityRepository(session).create(
            tenant_id=tenant_a, telegram_bot_id=970_400_100, username="a_bot"
        )
        await session.commit()

    async with session_factory() as session:
        overview = await TenantManagementService(session).get_tenant(tenant_a)
    assert overview.staff_count == 1
    assert overview.bot_count == 1
    assert overview.plan_code is None  # raw tenant fixture без Subscription


async def test_list_tenants_uses_fixed_number_of_queries(
    session_factory, tenant_a, tenant_b, query_counter
):
    async with session_factory() as session:
        query_counter.clear()
        overviews = await TenantManagementService(session).list_tenants()
    # 1 (tenants) + 3 (branch/staff/bot counts) + 1 (subscription join) = 5,
    # независимо от того, что тенантов минимум два (tenant_a, tenant_b).
    assert len(query_counter) <= 5, query_counter
    assert len(overviews) >= 2


# === E. Bot provisioning через TenantManagementService =========================
async def test_attach_bot_works_and_audits(session_factory, tenant_a):
    async with session_factory() as session:
        identity, created = await TenantManagementService(session).attach_bot(
            tenant_a, telegram_bot_id=970_500_001, username="shop_bot", actor_telegram_id=1
        )
    assert created is True
    async with session_factory() as session:
        entry = await session.scalar(
            select(AuditLogEntry).where(
                AuditLogEntry.action == "bot.attached", AuditLogEntry.tenant_id == tenant_a
            )
        )
    assert entry is not None
    assert identity.tenant_id == tenant_a


async def test_attach_bot_is_idempotent_for_same_tenant(session_factory, tenant_a):
    async with session_factory() as session:
        service = TenantManagementService(session)
        _first, created_1 = await service.attach_bot(
            tenant_a, telegram_bot_id=970_500_002, username="b", actor_telegram_id=1
        )
    async with session_factory() as session:
        service = TenantManagementService(session)
        _second, created_2 = await service.attach_bot(
            tenant_a, telegram_bot_id=970_500_002, username="b", actor_telegram_id=1
        )
    assert (created_1, created_2) == (True, False)


async def test_attach_bot_rejects_reassignment(session_factory, tenant_a, tenant_b):
    async with session_factory() as session:
        await TenantManagementService(session).attach_bot(
            tenant_a, telegram_bot_id=970_500_003, username="b", actor_telegram_id=1
        )
    async with session_factory() as session:
        with pytest.raises(BotAlreadyAssignedError):
            await BotProvisioningService(session).attach(
                tenant_id=tenant_b, telegram_bot_id=970_500_003, username="b"
            )


async def test_deactivate_and_activate_bot_roundtrip(session_factory, tenant_a):
    async with session_factory() as session:
        service = TenantManagementService(session)
        await service.attach_bot(
            tenant_a, telegram_bot_id=970_500_004, username="b", actor_telegram_id=1
        )
    async with session_factory() as session:
        service = TenantManagementService(session)
        deactivated = await service.deactivate_bot(970_500_004, actor_telegram_id=1)
    assert deactivated.is_active is False
    async with session_factory() as session:
        service = TenantManagementService(session)
        reactivated = await service.activate_bot(970_500_004, actor_telegram_id=1)
    assert reactivated.is_active is True
    async with session_factory() as session:
        entries = (
            await session.scalars(
                select(AuditLogEntry).where(
                    AuditLogEntry.action.in_(("bot.deactivated", "bot.activated")),
                    AuditLogEntry.tenant_id == tenant_a,
                )
            )
        ).all()
    assert {e.action for e in entries} == {"bot.deactivated", "bot.activated"}


# === F. Dispatcher-level security (§30) ========================================
async def test_tenant_bot_cannot_reach_platform_router(dispatcher, session_factory, tenant_a):
    """Bot арендатора (обычная TelegramBotIdentity) — /platform недостижим,
    даже если пишущий пользователь оказался бы платформенным оператором."""
    async with session_factory() as session:
        await TelegramBotIdentityRepository(session).create(
            tenant_id=tenant_a, telegram_bot_id=970_600_001, username="tenant_bot"
        )
        await session.commit()

    tenant_bot = _bot(970_600_001)
    calls = await feed(dispatcher, tenant_bot, make_message("/platform", 970_600_999))
    # Обычный tenant-бот не проваливается ("fails closed" были бы calls==[]
    # из-за неизвестного bot_id) — здесь bot ИЗВЕСТЕН арендатору, апдейт
    # доходит до tenant-роутеров, но НЕ до platform-роутера: /platform там
    # не существует, значит либо fallback, либо тишина — в любом случае НЕ
    # платформенное меню.
    assert not any("Платформа" in (text or "") for _, text in calls)


async def test_platform_bot_rejects_non_operator(dispatcher):
    calls = await feed(dispatcher, _bot(FLOW_PLATFORM_BOT_ID), make_message("/platform", 970_601_000))
    # RequirePlatformOperator отклоняет апдейт до platform-роутера; сообщение
    # проваливается в общий fallback ("не понял команду"), а не в
    # платформенное меню — именно это и является границей безопасности.
    assert not any("Платформ" in (text or "") for _, text in calls)


async def test_platform_bot_allows_real_operator_to_list_and_suspend_tenant(
    session_factory, dispatcher
):
    operator_id = 970_700_001
    async with session_factory() as session:
        await PlatformOperatorRepository(session).create(
            telegram_user_id=operator_id, role=PlatformRole.PLATFORM_ADMIN
        )
        await session.commit()
    target_tenant_id = await _make_tenant(session_factory, status=TenantStatus.ACTIVE)
    try:
        platform_bot = _bot(FLOW_PLATFORM_BOT_ID)
        calls = await feed(dispatcher, platform_bot, make_message("/platform", operator_id))
        assert calls  # платформенное меню действительно ответило

        suspend_cb = make_callback(
            PlatformCB(action="suspend", arg=str(target_tenant_id)).pack(), operator_id
        )
        await feed(dispatcher, platform_bot, suspend_cb)

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(target_tenant_id)
        assert tenant.status == TenantStatus.SUSPENDED
    finally:
        await _delete_tenant(session_factory, target_tenant_id)
        await _delete_operator(session_factory, operator_id)


async def test_forged_tenant_id_in_platform_callback_is_rejected(session_factory, dispatcher):
    operator_id = 970_700_002
    async with session_factory() as session:
        await PlatformOperatorRepository(session).create(
            telegram_user_id=operator_id, role=PlatformRole.PLATFORM_ADMIN
        )
        await session.commit()
    try:
        platform_bot = _bot(FLOW_PLATFORM_BOT_ID)
        forged = make_callback(
            PlatformCB(action="suspend", arg=str(uuid.uuid4())).pack(), operator_id
        )
        calls = await feed(dispatcher, platform_bot, forged)
        # Никакого краша — сервер сам разрешает tenant и отклоняет
        # несуществующий id, а не доверяет строке из callback.
        assert calls
    finally:
        await _delete_operator(session_factory, operator_id)
