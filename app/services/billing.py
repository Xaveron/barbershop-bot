"""Провайдер-независимый биллинговый домен: подписка, фичи, лимиты.

Ничто здесь не знает о Stripe/Paddle/Telegram. Ошибки несут ключ i18n и
структурированные параметры (как BookingError/AuthorizationError), а не
готовый текст — хендлер сам решает, как показать это на языке пользователя
(см. docs/BILLING_DESIGN.md)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Appointment,
    AppointmentStatus,
    AuditLogEntry,
    Barber,
    BarberBranch,
    Branch,
    Feature,
    LimitKey,
    PlanFeature,
    Service,
    StaffMember,
    Subscription,
    SubscriptionStatus,
)
from app.database.repositories import PlanRepository, SubscriptionRepository
from app.utils.dt import now_utc
from app.utils.locks import advisory_lock_key

# Статусы, при которых арендатор всё ещё считается "эффективно активным"
# (см. docs/BILLING_DESIGN.md §Grace period) — PAST_DUE сюда входит
# намеренно: тенант может ещё какое-то время работать при просрочке оплаты,
# пока нет дозвона/дожима (dunning) — этого Phase 6 не строит, только сам
# предикат.
_EFFECTIVELY_ACTIVE_STATUSES = frozenset(
    {SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE}
)

# Захват advisory-lock перед подсчётом использования: короткие попытки, а не
# бесконечное ожидание — то же обоснование, что LOCK_ATTEMPTS в
# app/services/booking.py, но отдельная константа: создание филиала/сотрудника
# — редкое админ-действие, не путь бронирования под нагрузкой.
_LOCK_ATTEMPTS = 8
_LOCK_RETRY_MIN_DELAY = 0.02
_LOCK_RETRY_MAX_DELAY = 0.2

# Фиксированное смещение на LimitKey поверх базового ключа арендатора —
# разные лимиты одного арендатора не конкурируют друг с другом, разные
# арендаторы не конкурируют вовсе (см. docs/BILLING_DESIGN.md §Concurrency).
_LIMIT_LOCK_OFFSETS: dict[LimitKey, int] = {
    LimitKey.MAX_BRANCHES: 0,
    LimitKey.MAX_BARBERS: 1,
    LimitKey.MAX_STAFF: 2,
    LimitKey.MAX_SERVICES: 3,
    LimitKey.MAX_MONTHLY_APPOINTMENTS: 4,
}

DEFAULT_PLAN_CODE = "free"
LEGACY_PLAN_CODE = "legacy"


class BillingError(Exception):
    """Аналог BookingError/AuthorizationError: несёт ключ i18n, а не готовый текст."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


class FeatureNotAvailable(BillingError):
    def __init__(self, feature: Feature) -> None:
        super().__init__("billing.feature_not_available", feature=feature.value)
        self.feature = feature


class SubscriptionInactive(BillingError):
    pass


class PlanLimitExceeded(BillingError):
    def __init__(self, limit_key: LimitKey, current: int, maximum: int) -> None:
        super().__init__(
            "billing.limit_reached",
            limit_key=limit_key.value,
            current=current,
            maximum=maximum,
        )
        self.limit_key = limit_key
        self.current = current
        self.maximum = maximum


def is_effectively_active(status: SubscriptionStatus) -> bool:
    """Чистая функция без I/O — детерминированное правило для будущего
    grace-period (см. docs/BILLING_DESIGN.md §Grace period). Ничто в Phase 6
    само не переводит подписку в PAST_DUE/CANCELED/EXPIRED — предикат готов
    для будущего платёжного вебхука, который будет это делать."""
    return status in _EFFECTIVELY_ACTIVE_STATUSES


class SubscriptionService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.subscriptions = SubscriptionRepository(session, tenant_id)
        self.plans = PlanRepository(session)

    async def get_or_create_default(self) -> Subscription:
        """Защитная сетка: в штатной работе у арендатора уже есть подписка
        (создана в TenantOnboardingService.create_tenant либо бэкфиллом
        миграции 0010) — этот метод существует на случай, если её почему-то
        нет, а не как основной путь создания (см. docs/BILLING_DESIGN.md §H)."""
        existing = await self.subscriptions.get()
        if existing is not None:
            return existing
        plan = await self.plans.get_by_code(DEFAULT_PLAN_CODE)
        if plan is None:
            raise RuntimeError(f"Тариф по умолчанию '{DEFAULT_PLAN_CODE}' не найден в каталоге.")
        subscription = await self.subscriptions.create(
            plan_id=plan.id, status=SubscriptionStatus.ACTIVE, current_period_start=now_utc()
        )
        # Проставляем связь вручную, как BookingService.create_appointment:
        # объект новый, ленивая подгрузка .plan после commit в
        # async-контексте недопустима, а Plan уже на руках.
        subscription.plan = plan
        # В отличие от репозиториев (flush, коммитит вызывающий), здесь
        # коммитим сами: get_or_create_default вызывается и из read-only
        # экрана «Тариф» (app/bot/handlers/admin/billing.py), у которого нет
        # своего коммита — без этого созданная по умолчанию подписка тихо
        # откатилась бы вместе с закрытием сессии.
        await self.session.commit()
        return subscription

    async def change_plan(
        self, *, plan_code: str, actor_telegram_id: int
    ) -> Subscription:
        """Не проверяет права вызывающего — как StaffService, это
        ответственность вызывающего кода (AuthorizationService.require(...,
        MANAGE_SUBSCRIPTION) до вызова)."""
        plan = await self.plans.get_by_code(plan_code)
        if plan is None:
            raise ValueError(f"Неизвестный тариф: {plan_code}")
        subscription = await self.get_or_create_default()
        old_plan_id = subscription.plan_id
        subscription.plan_id = plan.id
        self.session.add(
            AuditLogEntry(
                tenant_id=self.tenant_id,
                actor_telegram_id=actor_telegram_id,
                action="subscription.plan_changed",
                details={"old_plan_id": str(old_plan_id), "new_plan_id": str(plan.id)},
            )
        )
        await self.session.commit()
        await self.session.refresh(subscription)
        return subscription


class EntitlementService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.subscriptions = SubscriptionRepository(session, tenant_id)

    async def has_feature(self, feature: Feature) -> bool:
        subscription = await self.subscriptions.get()
        if subscription is None:
            # Отсутствие подписки — аномалия (Subscription создаётся и
            # онбордингом, и бэкфиллом миграции 0010), а не обычный случай.
            # Fail-open, а не -closed: тот же принцип, что get_limit
            # возвращает None ("без ограничений") без подписки — не
            # блокируем работу арендатора из-за отсутствующих/сломанных
            # биллинговых данных (см. §43 docs/BILLING_DESIGN.md).
            return True
        stmt = select(func.count()).select_from(PlanFeature).where(
            PlanFeature.plan_id == subscription.plan_id, PlanFeature.feature == feature
        )
        return bool(await self.session.scalar(stmt))

    async def require_feature(self, feature: Feature) -> None:
        if not await self.has_feature(feature):
            raise FeatureNotAvailable(feature)


class LimitService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.subscriptions = SubscriptionRepository(session, tenant_id)

    async def get_limit(self, key: LimitKey) -> int | None:
        """None означает «без ограничений» — как отсутствие строки PlanLimit
        для этого ключа (безопасный дефолт, см. docs/BILLING_DESIGN.md §43),
        так и явная строка со значением NULL."""
        subscription = await self.subscriptions.get()
        if subscription is None:
            return None
        for limit in subscription.plan.limits:
            if limit.limit_key == key:
                return limit.value
        return None

    async def get_usage(self, key: LimitKey) -> int:
        counters = {
            LimitKey.MAX_BRANCHES: self._count_active_branches,
            LimitKey.MAX_BARBERS: self._count_bookable_barbers,
            LimitKey.MAX_STAFF: self._count_active_staff,
            LimitKey.MAX_SERVICES: self._count_active_services,
            LimitKey.MAX_MONTHLY_APPOINTMENTS: self._count_monthly_appointments,
        }
        return await counters[key]()

    async def assert_can_create(self, key: LimitKey, *, increment: int = 1) -> None:
        """Блокировка (tenant_id, key) до подсчёта — иначе COUNT потом INSERT
        не атомарны, и два одновременных запроса оба увидят N и оба создадут
        N+1-ю запись (см. docs/BILLING_DESIGN.md §Concurrency)."""
        lock_key = advisory_lock_key(self.tenant_id) + _LIMIT_LOCK_OFFSETS[key]
        if not await self._try_lock(lock_key):
            raise BillingError("billing.try_again")

        limit = await self.get_limit(key)
        if limit is None:
            return
        usage = await self.get_usage(key)
        if usage + increment > limit:
            raise PlanLimitExceeded(limit_key=key, current=usage, maximum=limit)

    async def _try_lock(self, lock_key: int) -> bool:
        for attempt in range(_LOCK_ATTEMPTS):
            acquired = await self.session.scalar(
                text("SELECT pg_try_advisory_xact_lock(CAST(:lock_key AS bigint))"),
                {"lock_key": lock_key},
            )
            if acquired:
                return True
            delay = min(_LOCK_RETRY_MIN_DELAY * 2**attempt, _LOCK_RETRY_MAX_DELAY)
            await asyncio.sleep(delay)
        return False

    # --- Подсчёт использования: агрегаты, без N+1 (см. docs/BILLING_DESIGN.md §Performance) ---
    async def _count_active_branches(self) -> int:
        stmt = select(func.count()).select_from(Branch).where(
            Branch.tenant_id == self.tenant_id, Branch.is_active.is_(True)
        )
        return int(await self.session.scalar(stmt) or 0)

    async def _count_bookable_barbers(self) -> int:
        """«Бронируемый» = активен и привязан хотя бы к одному активному
        филиалу — тот же предикат, что
        TenantOnboardingService._has_bookable_barber (Phase 5), здесь как COUNT DISTINCT."""
        stmt = (
            select(func.count(func.distinct(Barber.id)))
            .select_from(Barber)
            .join(BarberBranch, BarberBranch.barber_id == Barber.id)
            .join(Branch, Branch.id == BarberBranch.branch_id)
            .where(
                Barber.tenant_id == self.tenant_id,
                Barber.is_active.is_(True),
                BarberBranch.tenant_id == self.tenant_id,
                Branch.is_active.is_(True),
            )
        )
        return int(await self.session.scalar(stmt) or 0)

    async def _count_active_staff(self) -> int:
        stmt = select(func.count()).select_from(StaffMember).where(
            StaffMember.tenant_id == self.tenant_id, StaffMember.is_active.is_(True)
        )
        return int(await self.session.scalar(stmt) or 0)

    async def _count_active_services(self) -> int:
        stmt = select(func.count()).select_from(Service).where(
            Service.tenant_id == self.tenant_id, Service.is_active.is_(True)
        )
        return int(await self.session.scalar(stmt) or 0)

    async def _count_monthly_appointments(self) -> int:
        """Текущий календарный месяц по UTC, только CONFIRMED/COMPLETED —
        см. docs/BILLING_DESIGN.md §Usage model за обоснованием (не
        Subscription.current_period_*, не CANCELLED/NO_SHOW)."""
        month_start, month_end = _current_utc_month_bounds()
        stmt = select(func.count()).select_from(Appointment).where(
            Appointment.tenant_id == self.tenant_id,
            Appointment.starts_at >= month_start,
            Appointment.starts_at < month_end,
            Appointment.status.in_((AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED)),
        )
        return int(await self.session.scalar(stmt) or 0)


def _current_utc_month_bounds() -> tuple[datetime, datetime]:
    now = now_utc()
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    return start, end
