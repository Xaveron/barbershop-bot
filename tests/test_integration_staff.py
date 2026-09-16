"""Интеграционные тесты RBAC на реальном PostgreSQL: изоляция арендаторов,
IDOR-защита репозитория, запись в audit log.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, select

from app.config import Settings
from app.database import build_engine, build_session_factory
from app.database.models import AuditLogEntry, Barber, Role, StaffMember, Tenant
from app.database.repositories import StaffRepository
from app.services.staff import StaffLifecycleError, StaffService

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — интеграционные тесты пропущены"
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
        ADMIN_ID="111111",
        TIMEZONE="Europe/Chisinau",
    )


@pytest.fixture
async def engine(settings: Settings):
    engine = build_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return build_session_factory(engine)


@pytest.fixture
async def tenant_id(session_factory):
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        tenant = Tenant(name=f"Test Tenant {marker}", slug=f"test-{marker}")
        session.add(tenant)
        await session.commit()
        tid = tenant.id
    yield tid
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tid))
        await session.commit()


async def test_staff_members_are_isolated_between_tenants(session_factory):
    """Один и тот же telegram_id — независимые сотрудники в разных арендаторах."""
    async with session_factory() as session:
        tenant_a = Tenant(name="Tenant A", slug=f"a-{uuid.uuid4().hex[:8]}")
        tenant_b = Tenant(name="Tenant B", slug=f"b-{uuid.uuid4().hex[:8]}")
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id

        staff_a = await StaffRepository(session, tenant_a_id).create(
            telegram_id=600_100, role=Role.TENANT_OWNER
        )
        staff_b = await StaffRepository(session, tenant_b_id).create(
            telegram_id=600_100, role=Role.RECEPTIONIST
        )
        await session.commit()

    try:
        assert staff_a is not None and staff_b is not None
        assert staff_a.id != staff_b.id
        async with session_factory() as session:
            found_a = await StaffRepository(session, tenant_a_id).get_by_telegram_id(600_100)
            found_b = await StaffRepository(session, tenant_b_id).get_by_telegram_id(600_100)
            assert found_a is not None and found_a.role == Role.TENANT_OWNER
            assert found_b is not None and found_b.role == Role.RECEPTIONIST
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(StaffMember).where(StaffMember.telegram_id == 600_100)
            )
            await cleanup.execute(
                delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
            )
            await cleanup.commit()


async def test_staff_get_rejects_id_from_another_tenant(session_factory):
    """IDOR: точный UUID чужого сотрудника не должен резолвиться через чужой tenant_id."""
    async with session_factory() as session:
        tenant_a = Tenant(name="Tenant A", slug=f"a-{uuid.uuid4().hex[:8]}")
        tenant_b = Tenant(name="Tenant B", slug=f"b-{uuid.uuid4().hex[:8]}")
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id

        staff_b = await StaffRepository(session, tenant_b_id).create(
            telegram_id=600_200, role=Role.MANAGER
        )
        await session.commit()
        staff_b_id = staff_b.id

    try:
        async with session_factory() as session:
            assert await StaffRepository(session, tenant_a_id).get(staff_b_id) is None
            assert await StaffRepository(session, tenant_b_id).get(staff_b_id) is not None
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(StaffMember).where(StaffMember.id == staff_b_id))
            await cleanup.execute(
                delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
            )
            await cleanup.commit()


async def test_staff_create_rejects_barber_from_another_tenant(session_factory):
    """Тот же класс дыры, что был найден и исправлен в ScheduleRepository
    (Phase 1.5 audit): создание сотрудника с barber_id чужого арендатора
    должно возвращать None, а не создавать перекрёстную ссылку."""
    async with session_factory() as session:
        tenant_a = Tenant(name="Tenant A", slug=f"a-{uuid.uuid4().hex[:8]}")
        tenant_b = Tenant(name="Tenant B", slug=f"b-{uuid.uuid4().hex[:8]}")
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id

        barber_b = Barber(tenant_id=tenant_b_id, name="Barber B")
        session.add(barber_b)
        await session.commit()
        barber_b_id = barber_b.id

    try:
        async with session_factory() as session:
            staff = await StaffRepository(session, tenant_a_id).create(
                telegram_id=600_300, role=Role.BARBER, barber_id=barber_b_id
            )
            assert staff is None

        async with session_factory() as session:
            leaked = await session.scalar(
                select(StaffMember).where(StaffMember.barber_id == barber_b_id)
            )
            assert leaked is None
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(Barber).where(Barber.id == barber_b_id))
            await cleanup.execute(
                delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
            )
            await cleanup.commit()


async def test_staff_service_create_writes_audit_log_entry(session_factory, tenant_id):
    async with session_factory() as session:
        staff = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=600_400, role=Role.RECEPTIONIST
        )
        assert staff is not None

    try:
        async with session_factory() as session:
            entry = await session.scalar(
                select(AuditLogEntry).where(
                    AuditLogEntry.tenant_id == tenant_id,
                    AuditLogEntry.action == "staff.created",
                    AuditLogEntry.target_telegram_id == 600_400,
                )
            )
            assert entry is not None
            assert entry.actor_telegram_id == 111111
            assert entry.details == {"role": "receptionist"}
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(AuditLogEntry).where(AuditLogEntry.target_telegram_id == 600_400)
            )
            await cleanup.execute(
                delete(StaffMember).where(StaffMember.telegram_id == 600_400)
            )
            await cleanup.commit()


async def test_staff_service_change_role_and_deactivate_are_logged(session_factory, tenant_id):
    async with session_factory() as session:
        staff = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=600_500, role=Role.RECEPTIONIST
        )
        assert staff is not None
        staff_id = staff.id

    try:
        async with session_factory() as session:
            service = StaffService(session, tenant_id)
            staff = await StaffRepository(session, tenant_id).get(staff_id)
            await service.change_role(
                actor_telegram_id=111111, staff=staff, new_role=Role.MANAGER
            )
            await service.deactivate(actor_telegram_id=111111, staff=staff)

        async with session_factory() as session:
            refreshed = await StaffRepository(session, tenant_id).get(staff_id)
            assert refreshed.role == Role.MANAGER
            assert refreshed.is_active is False

            role_change = await session.scalar(
                select(AuditLogEntry).where(
                    AuditLogEntry.tenant_id == tenant_id,
                    AuditLogEntry.action == "staff.role_changed",
                    AuditLogEntry.target_telegram_id == 600_500,
                )
            )
            assert role_change is not None
            assert role_change.details == {"old_role": "receptionist", "new_role": "manager"}

            deactivation = await session.scalar(
                select(AuditLogEntry).where(
                    AuditLogEntry.tenant_id == tenant_id,
                    AuditLogEntry.action == "staff.deactivated",
                    AuditLogEntry.target_telegram_id == 600_500,
                )
            )
            assert deactivation is not None
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(AuditLogEntry).where(AuditLogEntry.target_telegram_id == 600_500)
            )
            await cleanup.execute(delete(StaffMember).where(StaffMember.id == staff_id))
            await cleanup.commit()


# --- Last-owner protection (Phase 9A §H-2) ----------------------------------
# Частичный уникальный индекс uq_staff_members_tenant_id_owner (миграция
# 0009) допускает не более одной строки role='tenant_owner' на арендатора
# вообще (активной или нет) — поэтому "другой активный владелец одновременно
# с текущим" структурно недостижим без правки схемы (запрещена в этой фазе).
# Тесты 3/4 из спецификации ("owner can be demoted/deactivated when another
# owner exists") реализованы как ближайший достижимый и осмысленный аналог:
# защита не блокирует операции над сотрудником, который НЕ является текущим
# владельцем — именно это и означает "другой владелец существует и не
# затронут".


async def test_sole_active_owner_cannot_be_demoted(session_factory, tenant_id):
    async with session_factory() as session:
        owner = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=600_600, role=Role.TENANT_OWNER
        )
        owner_id = owner.id

    try:
        async with session_factory() as session:
            service = StaffService(session, tenant_id)
            owner = await StaffRepository(session, tenant_id).get(owner_id)
            with pytest.raises(StaffLifecycleError):
                await service.change_role(
                    actor_telegram_id=111111, staff=owner, new_role=Role.MANAGER
                )
        async with session_factory() as session:
            refreshed = await StaffRepository(session, tenant_id).get(owner_id)
            assert refreshed.role == Role.TENANT_OWNER
            assert refreshed.is_active is True
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(StaffMember).where(StaffMember.id == owner_id))
            await cleanup.commit()


async def test_sole_active_owner_cannot_be_deactivated(session_factory, tenant_id):
    async with session_factory() as session:
        owner = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=600_700, role=Role.TENANT_OWNER
        )
        owner_id = owner.id

    try:
        async with session_factory() as session:
            service = StaffService(session, tenant_id)
            owner = await StaffRepository(session, tenant_id).get(owner_id)
            with pytest.raises(StaffLifecycleError):
                await service.deactivate(actor_telegram_id=111111, staff=owner)
        async with session_factory() as session:
            refreshed = await StaffRepository(session, tenant_id).get(owner_id)
            assert refreshed.is_active is True
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(StaffMember).where(StaffMember.id == owner_id))
            await cleanup.commit()


async def test_change_role_allowed_for_non_owner_staff(session_factory, tenant_id):
    """Аналог пункта 3 спецификации: защита владельца не мешает менять роль
    сотрудника, который сам владельцем не является — "другой владелец
    арендатора" (созданный тут же) при этом остаётся нетронутым."""
    async with session_factory() as session:
        owner = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=600_800, role=Role.TENANT_OWNER
        )
        manager = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=600_801, role=Role.MANAGER
        )
        owner_id, manager_id = owner.id, manager.id

    try:
        async with session_factory() as session:
            service = StaffService(session, tenant_id)
            manager = await StaffRepository(session, tenant_id).get(manager_id)
            await service.change_role(
                actor_telegram_id=111111, staff=manager, new_role=Role.RECEPTIONIST
            )
        async with session_factory() as session:
            refreshed_manager = await StaffRepository(session, tenant_id).get(manager_id)
            refreshed_owner = await StaffRepository(session, tenant_id).get(owner_id)
            assert refreshed_manager.role == Role.RECEPTIONIST
            assert refreshed_owner.role == Role.TENANT_OWNER
            assert refreshed_owner.is_active is True
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(StaffMember).where(StaffMember.id.in_((owner_id, manager_id)))
            )
            await cleanup.commit()


async def test_deactivate_allowed_for_non_owner_staff(session_factory, tenant_id):
    """Аналог пункта 4 спецификации: тот же смысл, что и предыдущий тест, но
    для деактивации."""
    async with session_factory() as session:
        owner = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=600_900, role=Role.TENANT_OWNER
        )
        manager = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=600_901, role=Role.MANAGER
        )
        owner_id, manager_id = owner.id, manager.id

    try:
        async with session_factory() as session:
            service = StaffService(session, tenant_id)
            manager = await StaffRepository(session, tenant_id).get(manager_id)
            await service.deactivate(actor_telegram_id=111111, staff=manager)
        async with session_factory() as session:
            refreshed_manager = await StaffRepository(session, tenant_id).get(manager_id)
            refreshed_owner = await StaffRepository(session, tenant_id).get(owner_id)
            assert refreshed_manager.is_active is False
            assert refreshed_owner.is_active is True
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(StaffMember).where(StaffMember.id.in_((owner_id, manager_id)))
            )
            await cleanup.commit()


async def test_owner_guard_is_tenant_scoped(session_factory):
    """Владелец другого арендатора не может ни защитить, ни "разблокировать"
    операцию над владельцем ЭТОГО арендатора — проверка идёт строго через
    StaffRepository(session, tenant_id).get_owner(), тот же tenant_id."""
    async with session_factory() as session:
        tenant_a = Tenant(name="Tenant A", slug=f"a-{uuid.uuid4().hex[:8]}")
        tenant_b = Tenant(name="Tenant B", slug=f"b-{uuid.uuid4().hex[:8]}")
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id

        owner_a = await StaffService(session, tenant_a_id).create_staff(
            actor_telegram_id=111111, telegram_id=601_000, role=Role.TENANT_OWNER
        )
        owner_b = await StaffService(session, tenant_b_id).create_staff(
            actor_telegram_id=111111, telegram_id=601_001, role=Role.TENANT_OWNER
        )
        owner_a_id, owner_b_id = owner_a.id, owner_b.id

    try:
        async with session_factory() as session:
            service_a = StaffService(session, tenant_a_id)
            owner_a = await StaffRepository(session, tenant_a_id).get(owner_a_id)
            # Owner B существует и активен, но он принадлежит ДРУГОМУ
            # арендатору — не должен считаться "другим владельцем" tenant_a.
            with pytest.raises(StaffLifecycleError):
                await service_a.deactivate(actor_telegram_id=111111, staff=owner_a)

        async with session_factory() as session:
            refreshed_a = await StaffRepository(session, tenant_a_id).get(owner_a_id)
            refreshed_b = await StaffRepository(session, tenant_b_id).get(owner_b_id)
            assert refreshed_a.is_active is True
            assert refreshed_b.is_active is True
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(StaffMember).where(StaffMember.id.in_((owner_a_id, owner_b_id)))
            )
            await cleanup.execute(
                delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
            )
            await cleanup.commit()


async def test_inactive_owner_is_not_protected_by_guard(session_factory, tenant_id):
    """Пункт 6 спецификации: уже неактивный владелец не считается "активным
    владельцем" — операция над ним (например, смена роли в рамках уборки
    данных) не блокируется защитой единственного владельца."""
    async with session_factory() as session:
        owner = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=111111, telegram_id=601_100, role=Role.TENANT_OWNER
        )
        owner_id = owner.id
        # Деактивируем напрямую через репозиторий, в обход StaffService —
        # имитирует состояние "владелец уже неактивен по любой причине".
        owner.is_active = False
        await session.commit()

    try:
        async with session_factory() as session:
            service = StaffService(session, tenant_id)
            owner = await StaffRepository(session, tenant_id).get(owner_id)
            assert owner.is_active is False
            # Не должно поднять StaffLifecycleError — гвард пропускает уже
            # неактивного владельца.
            await service.change_role(
                actor_telegram_id=111111, staff=owner, new_role=Role.TENANT_ADMIN
            )
        async with session_factory() as session:
            refreshed = await StaffRepository(session, tenant_id).get(owner_id)
            assert refreshed.role == Role.TENANT_ADMIN
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(StaffMember).where(StaffMember.id == owner_id))
            await cleanup.commit()
