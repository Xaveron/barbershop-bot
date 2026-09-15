"""Тонкие обёртки создания филиала/барбера/услуги с проверкой лимита тарифа.

У Branch/Barber/Service нет собственного сервисного слоя (в отличие от
Staff/Booking) — сегодня админ-хендлеры вызывают репозиторий напрямую. Эти
классы — единственная точка, где план (LimitService.assert_can_create)
проверяется ПЕРЕД созданием, так что будущий REST API/Mini App, вызвав их
вместо репозитория напрямую, не сможет обойти проверку так же, как не может
обойти её сегодняшний хендлер (см. docs/BILLING_DESIGN.md §Enforcement).

Названия классов намеренно не совпадают с уже существующими моделями
BranchService/BarberService (Phase 3/4 opt-out таблицы м2м) — это разные
сущности.

Коммит остаётся на вызывающем хендлере (как и раньше для голого репозитория)
— некоторые хендлеры делают доп. работу в той же транзакции после create
(например, автопривязка барбера к единственному филиалу в
admin/barbers.py), и её нельзя разрывать на два commit."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Barber, Branch, LimitKey, Service
from app.database.repositories import BarberRepository, BranchRepository, ServiceRepository
from app.services.billing import LimitService


class BranchProvisioningService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.limits = LimitService(session, tenant_id)
        self.repository = BranchRepository(session, tenant_id)

    async def create_branch(
        self,
        *,
        name: str,
        address: str | None = None,
        phone: str | None = None,
        timezone: str | None = None,
        currency: str | None = None,
    ) -> Branch:
        await self.limits.assert_can_create(LimitKey.MAX_BRANCHES)
        return await self.repository.create(
            name=name, address=address, phone=phone, timezone=timezone, currency=currency
        )


class BarberProvisioningService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.limits = LimitService(session, tenant_id)
        self.repository = BarberRepository(session, tenant_id)

    async def create_barber(self, *, name: str, description: str | None = None) -> Barber:
        await self.limits.assert_can_create(LimitKey.MAX_BARBERS)
        return await self.repository.create(name=name, description=description)


class ServiceProvisioningService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.limits = LimitService(session, tenant_id)
        self.repository = ServiceRepository(session, tenant_id)

    async def create_service(
        self,
        *,
        name: str,
        duration_minutes: int,
        price: Decimal,
        description: str | None = None,
        currency: str = "MDL",
    ) -> Service:
        await self.limits.assert_can_create(LimitKey.MAX_SERVICES)
        return await self.repository.create(
            name=name,
            duration_minutes=duration_minutes,
            price=price,
            description=description,
            currency=currency,
        )
