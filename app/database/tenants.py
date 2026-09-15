"""Разрешение текущего арендатора при старте процесса (Phase 1: ровно один)."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.repositories.tenant import TenantRepository
from app.services.onboarding import TenantOnboardingService

logger = logging.getLogger(__name__)


async def resolve_default_tenant_id(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> uuid.UUID:
    """Арендатор из уже существующей строки — поведение не меняется для
    любой сегодняшней инсталляции (миграция 0004 уже создаёт её). Если
    строк нет вообще (гипотетическая свежая БД без этого исторического
    бэкфилла), самостоятельно создаёт ОДИН арендатор в статусе ONBOARDING,
    засеянный из Settings — тем же набором полей, что и миграция 0004,
    только на уровне рантайма, а не миграции (см.
    docs/TENANT_ONBOARDING_DESIGN.md §3)."""
    async with session_factory() as session:
        tenant = await TenantRepository(session).get_default()
        if tenant is not None:
            return tenant.id

        logger.warning(
            "В базе нет ни одного арендатора — создаём новый в статусе ONBOARDING "
            "из текущих настроек (see docs/TENANT_ONBOARDING_DESIGN.md)."
        )
        tenant = await TenantOnboardingService.create_tenant(
            session,
            name=settings.shop_name or "Default Tenant",
            slug="default",
            timezone=settings.timezone,
            currency=settings.default_currency,
        )
        return tenant.id
