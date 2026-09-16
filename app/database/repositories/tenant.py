from __future__ import annotations

import uuid

from sqlalchemy import func, select

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

    async def list_all(self, *, limit: int | None = None, offset: int = 0) -> list[Tenant]:
        """Платформенный обзор (Phase 8) — все арендаторы, не один tenant_id.
        limit=None — полный список; limit задан — одна страница платформенного
        списка (см. Phase 9C §M-6). id как tie-breaker для стабильного порядка."""
        stmt = select(Tenant).order_by(Tenant.created_at, Tenant.id)
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))

    async def count_all(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(Tenant)) or 0

    async def slug_exists(self, slug: str) -> bool:
        return await self.session.scalar(select(Tenant.id).where(Tenant.slug == slug)) is not None
