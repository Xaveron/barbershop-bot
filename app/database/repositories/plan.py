from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import Plan
from app.database.repositories.base import BaseRepository


class PlanRepository(BaseRepository):
    """Каталог тарифов — платформенный, не арендаторский: не наследует
    TenantScopedRepository (см. docs/BILLING_DESIGN.md §Database design)."""

    async def get(self, plan_id: uuid.UUID) -> Plan | None:
        return await self.session.get(Plan, plan_id)

    async def get_by_code(self, code: str) -> Plan | None:
        stmt = select(Plan).where(Plan.code == code)
        return await self.session.scalar(stmt)

    async def list_active(self) -> list[Plan]:
        stmt = select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.name)
        return list(await self.session.scalars(stmt))

    async def list_all(self) -> list[Plan]:
        """Включая неактивные (например LEGACY) — только для dev-инструмента
        SUPER_ADMIN (см. docs/BILLING_DESIGN.md §RBAC); обычный список
        тарифов для показа арендатору использует list_active()."""
        stmt = select(Plan).order_by(Plan.name)
        return list(await self.session.scalars(stmt))
