from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.database.models import Subscription, SubscriptionStatus
from app.database.repositories.base import TenantScopedRepository


class SubscriptionRepository(TenantScopedRepository):
    async def get(self) -> Subscription | None:
        """Ровно одна строка на арендатора (uq_subscriptions_tenant_id) —
        нет отдельного subscription_id, который нужно было бы передавать
        и тем самым открывать IDOR (см. docs/BILLING_DESIGN.md §Security)."""
        stmt = select(Subscription).where(Subscription.tenant_id == self.tenant_id)
        return await self.session.scalar(stmt)

    async def create(
        self,
        *,
        plan_id: uuid.UUID,
        status: SubscriptionStatus,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
    ) -> Subscription:
        subscription = Subscription(
            tenant_id=self.tenant_id,
            plan_id=plan_id,
            status=status,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
        )
        self.session.add(subscription)
        await self.session.flush()
        return subscription
