from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database.models import Barber, BarberService, Service
from app.database.repositories.base import TenantScopedRepository


class BarberServiceRepository(TenantScopedRepository):
    async def _belongs_to_tenant(self, model, entity_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(model).where(
            model.id == entity_id, model.tenant_id == self.tenant_id
        )
        return bool(await self.session.scalar(stmt))

    async def barber_provides_service(
        self, *, barber_id: uuid.UUID, service_id: uuid.UUID
    ) -> bool:
        """Отсутствие строки означает «предоставляет» (opt-out, см. docstring
        BarberService) — симметрично BranchRepository.service_available_at_branch."""
        stmt = select(BarberService.is_active).where(
            BarberService.tenant_id == self.tenant_id,
            BarberService.barber_id == barber_id,
            BarberService.service_id == service_id,
        )
        row = await self.session.scalar(stmt)
        return True if row is None else row

    async def set_active(
        self, *, barber_id: uuid.UUID, service_id: uuid.UUID, is_active: bool
    ) -> BarberService | None:
        """Тот же guard-паттерн, что BranchRepository.assign_service."""
        if not await self._belongs_to_tenant(Barber, barber_id):
            return None
        if not await self._belongs_to_tenant(Service, service_id):
            return None
        existing = await self.session.scalar(
            select(BarberService).where(
                BarberService.tenant_id == self.tenant_id,
                BarberService.barber_id == barber_id,
                BarberService.service_id == service_id,
            )
        )
        if existing is not None:
            existing.is_active = is_active
            await self.session.flush()
            return existing
        link = BarberService(
            tenant_id=self.tenant_id, barber_id=barber_id, service_id=service_id,
            is_active=is_active,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def list_disabled_for_barber(self, barber_id: uuid.UUID) -> list[BarberService]:
        """Явные отказы (is_active=False) — единственные строки, которые
        когда-либо нужно показать в админке: остальное — «предоставляет» по умолчанию."""
        stmt = select(BarberService).where(
            BarberService.tenant_id == self.tenant_id,
            BarberService.barber_id == barber_id,
            BarberService.is_active.is_(False),
        )
        return list(await self.session.scalars(stmt))
