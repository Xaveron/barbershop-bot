"""Разрешение текущего арендатора при старте процесса (Phase 1: ровно один)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.repositories.tenant import TenantRepository


async def resolve_default_tenant_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    async with session_factory() as session:
        tenant = await TenantRepository(session).get_default()
    if tenant is None:
        raise RuntimeError(
            "В базе нет ни одного арендатора. Примените миграции: "
            "`alembic upgrade head` (0004 создаёт арендатора по умолчанию)."
        )
    return tenant.id
