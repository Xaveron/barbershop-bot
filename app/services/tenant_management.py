"""Платформенные операции над арендаторами (Phase 8).

Не дублирует TenantOnboardingService — переиспользует его для create/
activate/ensure_owner (см. docs/PLATFORM_CONTROL_PLANE.md). Единственная
здесь по-настоящему новая операция — suspend_tenant (ничего не
приостанавливает сегодня) и агрегированный обзор арендаторов для платформы."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AuditLogEntry,
    Branch,
    Plan,
    StaffMember,
    Subscription,
    SubscriptionStatus,
    TelegramBotIdentity,
    Tenant,
    TenantStatus,
)
from app.database.repositories import TenantRepository
from app.services.bot_identity import BotProvisioningService
from app.services.onboarding import OnboardingReadiness, TenantOnboardingService

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class TenantLifecycleError(Exception):
    """Аналог BookingError/AuthorizationError: несёт ключ перевода, а не
    готовый текст."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


@dataclass(slots=True)
class TenantOverview:
    """Операционный обзор одного арендатора для платформы — без customer
    data, без токенов (см. docs/PLATFORM_CONTROL_PLANE.md §13)."""

    id: uuid.UUID
    name: str
    slug: str
    status: TenantStatus
    timezone: str
    currency: str
    branch_count: int
    staff_count: int
    bot_count: int
    plan_code: str | None
    subscription_status: SubscriptionStatus | None


def _slugify(name: str, suffix: str) -> str:
    base = _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "tenant"
    return f"{base}-{suffix}"


class TenantManagementService:
    """Не tenant-scoped по конструкции — управляет множеством арендаторов,
    tenant_id передаётся явно в каждый метод, которому он нужен."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tenants = TenantRepository(session)

    # --- Обзор -------------------------------------------------------------
    async def list_tenants(
        self, *, limit: int | None = None, offset: int = 0
    ) -> list[TenantOverview]:
        """limit=None — полный список; limit задан — одна страница
        платформенного списка (см. Phase 9C §M-6)."""
        tenants = await self.tenants.list_all(limit=limit, offset=offset)
        return await self._build_overviews(tenants)

    async def count_tenants(self) -> int:
        return await self.tenants.count_all()

    async def get_tenant(self, tenant_id: uuid.UUID) -> TenantOverview | None:
        tenant = await self.tenants.get(tenant_id)
        if tenant is None:
            return None
        overviews = await self._build_overviews([tenant])
        return overviews[0]

    async def _build_overviews(self, tenants: list[Tenant]) -> list[TenantOverview]:
        """Фиксированное число агрегатных запросов независимо от количества
        арендаторов — не один запрос на арендатора (см. §13/§36)."""
        if not tenants:
            return []
        tenant_ids = [t.id for t in tenants]

        branch_counts = dict(
            (
                await self.session.execute(
                    select(Branch.tenant_id, func.count())
                    .where(Branch.tenant_id.in_(tenant_ids), Branch.is_active.is_(True))
                    .group_by(Branch.tenant_id)
                )
            ).all()
        )
        staff_counts = dict(
            (
                await self.session.execute(
                    select(StaffMember.tenant_id, func.count())
                    .where(
                        StaffMember.tenant_id.in_(tenant_ids), StaffMember.is_active.is_(True)
                    )
                    .group_by(StaffMember.tenant_id)
                )
            ).all()
        )
        bot_counts = dict(
            (
                await self.session.execute(
                    select(TelegramBotIdentity.tenant_id, func.count())
                    .where(
                        TelegramBotIdentity.tenant_id.in_(tenant_ids),
                        TelegramBotIdentity.is_active.is_(True),
                    )
                    .group_by(TelegramBotIdentity.tenant_id)
                )
            ).all()
        )
        subscriptions = (
            await self.session.execute(
                select(Subscription.tenant_id, Plan.code, Subscription.status)
                .join(Plan, Plan.id == Subscription.plan_id)
                .where(Subscription.tenant_id.in_(tenant_ids))
            )
        ).all()
        sub_by_tenant = {row.tenant_id: (row.code, row.status) for row in subscriptions}

        overviews = []
        for tenant in tenants:
            plan_code, sub_status = sub_by_tenant.get(tenant.id, (None, None))
            overviews.append(
                TenantOverview(
                    id=tenant.id,
                    name=tenant.name,
                    slug=tenant.slug,
                    status=tenant.status,
                    timezone=tenant.timezone,
                    currency=tenant.currency,
                    branch_count=branch_counts.get(tenant.id, 0),
                    staff_count=staff_counts.get(tenant.id, 0),
                    bot_count=bot_counts.get(tenant.id, 0),
                    plan_code=plan_code,
                    subscription_status=sub_status,
                )
            )
        return overviews

    # --- Создание / жизненный цикл ------------------------------------------
    async def create_tenant(self, *, name: str, actor_telegram_id: int) -> Tenant:
        """Делегирует TenantOnboardingService.create_tenant (Phase 5/6) —
        не дублирует его. Слаг подбирается автоматически и уникально: живой
        UI просит только название, не отдельный технический слаг (§8/§14)."""
        for _ in range(5):
            slug = _slugify(name, uuid.uuid4().hex[:6])
            if not await self.tenants.slug_exists(slug):
                break
        tenant = await TenantOnboardingService.create_tenant(self.session, name=name, slug=slug)
        self.session.add(
            AuditLogEntry(
                tenant_id=tenant.id, actor_telegram_id=actor_telegram_id, action="tenant.created"
            )
        )
        await self.session.commit()
        return tenant

    async def activate_tenant(
        self, tenant_id: uuid.UUID, *, actor_telegram_id: int
    ) -> OnboardingReadiness:
        """Прямой проброс на существующую валидацию готовности (Phase 5) —
        работает и для первой активации (ONBOARDING), и для реактивации
        (SUSPENDED): activate() не проверяет предыдущий статус, только
        «уже ACTIVE или нет» + готовность (см. §22)."""
        return await TenantOnboardingService(self.session, tenant_id).activate(
            actor_telegram_id=actor_telegram_id
        )

    async def suspend_tenant(self, tenant_id: uuid.UUID, *, actor_telegram_id: int) -> Tenant:
        tenant = await self.tenants.get(tenant_id)
        if tenant is None:
            raise TenantLifecycleError("platform.tenant_not_found")
        if tenant.status == TenantStatus.SUSPENDED:
            return tenant  # идемпотентный no-op (§19)
        if tenant.status != TenantStatus.ACTIVE:
            raise TenantLifecycleError(
                "platform.invalid_transition",
                from_status=tenant.status.value,
                to_status="suspended",
            )
        tenant.status = TenantStatus.SUSPENDED
        self.session.add(
            AuditLogEntry(
                tenant_id=tenant_id, actor_telegram_id=actor_telegram_id, action="tenant.suspended"
            )
        )
        await self.session.commit()
        return tenant

    async def ensure_owner(
        self, tenant_id: uuid.UUID, *, telegram_id: int, actor_telegram_id: int
    ) -> StaffMember:
        """Прямой проброс на TenantOnboardingService.ensure_owner (Phase 5) —
        уникальность владельца остаётся на уровне БД
        (uq_staff_members_tenant_id_owner), аудит — через
        StaffService.create_staff ("staff.created", details.role=tenant_owner
        — это и есть OWNER_ASSIGNED из §18, под уже существующим именем)."""
        return await TenantOnboardingService(self.session, tenant_id).ensure_owner(
            telegram_id=telegram_id, actor_telegram_id=actor_telegram_id
        )

    # --- Боты ----------------------------------------------------------------
    async def attach_bot(
        self,
        tenant_id: uuid.UUID,
        *,
        telegram_bot_id: int,
        username: str | None,
        actor_telegram_id: int,
    ) -> tuple[TelegramBotIdentity, bool]:
        identity, created = await BotProvisioningService(self.session).attach(
            tenant_id=tenant_id, telegram_bot_id=telegram_bot_id, username=username
        )
        if created:
            self.session.add(
                AuditLogEntry(
                    tenant_id=tenant_id,
                    actor_telegram_id=actor_telegram_id,
                    action="bot.attached",
                    details={"telegram_bot_id": telegram_bot_id, "username": username},
                )
            )
        await self.session.commit()
        return identity, created

    async def deactivate_bot(
        self, telegram_bot_id: int, *, actor_telegram_id: int
    ) -> TelegramBotIdentity | None:
        identity = await BotProvisioningService(self.session).deactivate(telegram_bot_id)
        if identity is not None:
            self.session.add(
                AuditLogEntry(
                    tenant_id=identity.tenant_id,
                    actor_telegram_id=actor_telegram_id,
                    action="bot.deactivated",
                    details={"telegram_bot_id": telegram_bot_id},
                )
            )
            await self.session.commit()
        return identity

    async def activate_bot(
        self, telegram_bot_id: int, *, actor_telegram_id: int
    ) -> TelegramBotIdentity | None:
        """Симметрично deactivate_bot — безопасно без токена: строка уже
        существует, восстанавливается только is_active (см. §11)."""
        identity = await BotProvisioningService(self.session).activate(telegram_bot_id)
        if identity is not None:
            self.session.add(
                AuditLogEntry(
                    tenant_id=identity.tenant_id,
                    actor_telegram_id=actor_telegram_id,
                    action="bot.activated",
                    details={"telegram_bot_id": telegram_bot_id},
                )
            )
            await self.session.commit()
        return identity
