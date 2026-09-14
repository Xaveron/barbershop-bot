from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.database.models import Appointment, AppointmentStatus, Service
from app.database.repositories.base import TenantScopedRepository


class ServiceRepository(TenantScopedRepository):
    async def get(self, service_id: uuid.UUID) -> Service | None:
        # session.get() — identity-map поиск только по PK, без доп. WHERE.
        # Здесь обязателен select(), иначе арендатор B смог бы прочитать
        # услугу арендатора A по известному UUID.
        stmt = select(Service).where(
            Service.id == service_id, Service.tenant_id == self.tenant_id
        )
        return await self.session.scalar(stmt)

    async def get_active(self, service_id: uuid.UUID) -> Service | None:
        service = await self.get(service_id)
        return service if service is not None and service.is_active else None

    async def list_active(self) -> list[Service]:
        stmt = (
            select(Service)
            .where(Service.tenant_id == self.tenant_id, Service.is_active.is_(True))
            .order_by(Service.sort_order, Service.name)
        )
        return list(await self.session.scalars(stmt))

    async def list_all(self) -> list[Service]:
        stmt = (
            select(Service)
            .where(Service.tenant_id == self.tenant_id)
            .order_by(Service.is_active.desc(), Service.sort_order, Service.name)
        )
        return list(await self.session.scalars(stmt))

    async def create(
        self,
        *,
        name: str,
        duration_minutes: int,
        price: Decimal,
        description: str | None = None,
        currency: str = "MDL",
    ) -> Service:
        service = Service(
            tenant_id=self.tenant_id,
            name=name,
            duration_minutes=duration_minutes,
            price=price,
            description=description,
            currency=currency,
        )
        self.session.add(service)
        await self.session.flush()
        return service

    async def has_appointments(self, service_id: uuid.UUID) -> bool:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.service_id == service_id,
                Appointment.tenant_id == self.tenant_id,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
        )
        return bool(await self.session.scalar(stmt))

    async def delete(self, service: Service) -> None:
        await self.session.delete(service)
        await self.session.flush()
