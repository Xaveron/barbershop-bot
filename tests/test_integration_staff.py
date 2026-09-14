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
from app.services.staff import StaffService

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
