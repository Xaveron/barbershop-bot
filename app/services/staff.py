"""Управление персоналом арендатора с записью в audit log.

Не проверяет права вызывающего — это ответственность вызывающего кода
(AuthorizationService.require(...) до вызова), как BookingService не
перепроверяет IsAdmin. Ни один хендлер не вызывает этот сервис в Phase 2 —
в приложении ещё нет UI управления персоналом (см. docs/RBAC_DESIGN.md §10);
это тестируемый сервисный слой на будущее.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLogEntry, LimitKey, Role, StaffMember
from app.database.repositories import StaffRepository
from app.services.billing import LimitService


class StaffService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.staff = StaffRepository(session, tenant_id)
        self.limits = LimitService(session, tenant_id)

    async def create_staff(
        self,
        *,
        actor_telegram_id: int,
        telegram_id: int,
        role: Role,
        barber_id: uuid.UUID | None = None,
    ) -> StaffMember | None:
        await self.limits.assert_can_create(LimitKey.MAX_STAFF)
        staff = await self.staff.create(telegram_id=telegram_id, role=role, barber_id=barber_id)
        if staff is None:
            await self.session.rollback()
            return None
        self.session.add(
            AuditLogEntry(
                tenant_id=self.tenant_id,
                actor_telegram_id=actor_telegram_id,
                action="staff.created",
                target_telegram_id=telegram_id,
                details={"role": role.value},
            )
        )
        await self.session.commit()
        return staff

    async def change_role(
        self, *, actor_telegram_id: int, staff: StaffMember, new_role: Role
    ) -> None:
        old_role = staff.role
        staff.role = new_role
        self.session.add(
            AuditLogEntry(
                tenant_id=self.tenant_id,
                actor_telegram_id=actor_telegram_id,
                action="staff.role_changed",
                target_telegram_id=staff.telegram_id,
                details={"old_role": old_role.value, "new_role": new_role.value},
            )
        )
        await self.session.commit()

    async def deactivate(self, *, actor_telegram_id: int, staff: StaffMember) -> None:
        staff.is_active = False
        self.session.add(
            AuditLogEntry(
                tenant_id=self.tenant_id,
                actor_telegram_id=actor_telegram_id,
                action="staff.deactivated",
                target_telegram_id=staff.telegram_id,
            )
        )
        await self.session.commit()
