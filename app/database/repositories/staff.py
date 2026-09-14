from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database.models import Barber, Role, StaffMember
from app.database.repositories.base import TenantScopedRepository


class StaffRepository(TenantScopedRepository):
    async def get(self, staff_id: uuid.UUID) -> StaffMember | None:
        # session.get() не умеет добавлять tenant_id в WHERE — обязателен select().
        stmt = select(StaffMember).where(
            StaffMember.id == staff_id, StaffMember.tenant_id == self.tenant_id
        )
        return await self.session.scalar(stmt)

    async def get_by_telegram_id(self, telegram_id: int) -> StaffMember | None:
        stmt = select(StaffMember).where(
            StaffMember.telegram_id == telegram_id, StaffMember.tenant_id == self.tenant_id
        )
        return await self.session.scalar(stmt)

    async def list_all(self) -> list[StaffMember]:
        stmt = (
            select(StaffMember)
            .where(StaffMember.tenant_id == self.tenant_id)
            .order_by(StaffMember.created_at)
        )
        return list(await self.session.scalars(stmt))

    async def create(
        self, *, telegram_id: int, role: Role, barber_id: uuid.UUID | None = None
    ) -> StaffMember | None:
        """Возвращает None, если barber_id указан, но принадлежит другому
        арендатору — тот же паттерн, что ScheduleRepository.set_day (см. Phase
        1.5 audit): «нет строки» и «чужой ресурс» не должны быть неразличимы."""
        if barber_id is not None and not await self._barber_belongs_to_tenant(barber_id):
            return None
        staff = StaffMember(
            tenant_id=self.tenant_id, telegram_id=telegram_id, role=role, barber_id=barber_id
        )
        self.session.add(staff)
        await self.session.flush()
        return staff

    async def _barber_belongs_to_tenant(self, barber_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(Barber).where(
            Barber.id == barber_id, Barber.tenant_id == self.tenant_id
        )
        return bool(await self.session.scalar(stmt))
