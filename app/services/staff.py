"""Управление персоналом арендатора с записью в audit log.

Не проверяет права вызывающего — это ответственность вызывающего кода
(AuthorizationService.require(...) до вызова), как BookingService не
перепроверяет IsAdmin. С Phase 9A этот сервис вызывается живым UI
(app/bot/handlers/admin/staff.py: добавление сотрудника, смена роли,
деактивация) — защита единственного владельца (_assert_not_sole_active_owner)
живёт здесь, на уровне сервиса, а не в хендлере, поэтому остаётся в силе даже
при подделанном callback.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLogEntry, LimitKey, Role, StaffMember
from app.database.repositories import StaffRepository
from app.services.billing import LimitService


class StaffLifecycleError(Exception):
    """Аналог AuthorizationError/BillingError: несёт ключ i18n, а не готовый
    текст — хендлер сам решает, как перевести и показать пользователю."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


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
        if new_role != Role.TENANT_OWNER:
            await self._assert_not_sole_active_owner(staff)
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
        await self._assert_not_sole_active_owner(staff)
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

    async def _assert_not_sole_active_owner(self, staff: StaffMember) -> None:
        """Нельзя понизить в роли/деактивировать TENANT_OWNER, если это
        оставит арендатора без единого активного владельца (см. Phase 9A
        §H-2). Частичный уникальный индекс uq_staff_members_tenant_id_owner
        (миграция 0009) допускает не более одной строки role='tenant_owner'
        на арендатора вообще (активной или нет) — на практике эта проверка
        всегда блокирует операцию над единственным владельцем. Написана в
        общем виде (считает активных владельцев через get_owner(), а не
        предполагает готовый факт "их ровно один"), чтобы остаться корректной
        и не требовать правки, если это ограничение когда-нибудь ослабят.

        Уже неактивный владелец (staff.is_active is False) не под защитой —
        деактивировать/понизить его в роли повторно безопасно."""
        if staff.role != Role.TENANT_OWNER or not staff.is_active:
            return
        current_owner = await self.staff.get_owner()
        if current_owner is None or current_owner.id == staff.id:
            raise StaffLifecycleError("staff.sole_owner_protected")
