from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database.models import Appointment, AppointmentStatus, Barber, BarberBranch
from app.database.repositories.base import TenantScopedRepository


class BarberRepository(TenantScopedRepository):
    async def get(self, barber_id: uuid.UUID) -> Barber | None:
        # session.get() не умеет добавлять tenant_id в WHERE — обязателен select().
        stmt = select(Barber).where(Barber.id == barber_id, Barber.tenant_id == self.tenant_id)
        return await self.session.scalar(stmt)

    async def get_active(self, barber_id: uuid.UUID) -> Barber | None:
        barber = await self.get(barber_id)
        return barber if barber is not None and barber.is_active else None

    async def list_active(self) -> list[Barber]:
        stmt = (
            select(Barber)
            .where(Barber.tenant_id == self.tenant_id, Barber.is_active.is_(True))
            .order_by(Barber.sort_order, Barber.name)
        )
        return list(await self.session.scalars(stmt))

    async def list_active_for_branch(self, branch_id: uuid.UUID) -> list[Barber]:
        stmt = (
            select(Barber)
            .join(BarberBranch, BarberBranch.barber_id == Barber.id)
            .where(
                Barber.tenant_id == self.tenant_id,
                Barber.is_active.is_(True),
                BarberBranch.tenant_id == self.tenant_id,
                BarberBranch.branch_id == branch_id,
            )
            .order_by(Barber.sort_order, Barber.name)
        )
        return list(await self.session.scalars(stmt))

    async def list_all(self) -> list[Barber]:
        stmt = (
            select(Barber)
            .where(Barber.tenant_id == self.tenant_id)
            .order_by(Barber.is_active.desc(), Barber.sort_order, Barber.name)
        )
        return list(await self.session.scalars(stmt))

    async def create(self, *, name: str, description: str | None = None) -> Barber:
        barber = Barber(tenant_id=self.tenant_id, name=name, description=description)
        self.session.add(barber)
        await self.session.flush()
        return barber

    async def has_appointments(self, barber_id: uuid.UUID) -> bool:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.barber_id == barber_id,
                Appointment.tenant_id == self.tenant_id,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
        )
        return bool(await self.session.scalar(stmt))

    async def delete(self, barber: Barber) -> None:
        await self.session.delete(barber)
        await self.session.flush()
