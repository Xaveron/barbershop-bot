from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import Tenant
from app.database.repositories.base import BaseRepository


class TenantRepository(BaseRepository):
    """Не может быть tenant-scoped — она сама разрешает арендатора."""

    async def get_default(self) -> Tenant | None:
        """Единственный арендатор в Phase 1 — самый старый по created_at."""
        stmt = select(Tenant).order_by(Tenant.created_at).limit(1)
        return await self.session.scalar(stmt)

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return await self.session.get(Tenant, tenant_id)
