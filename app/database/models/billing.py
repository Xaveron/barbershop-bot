"""Провайдер-независимый биллинговый домен (Phase 6).

Каталог (Plan/PlanFeature/PlanLimit) — глобальные таблицы без tenant_id:
тарифы принадлежат платформе, а не конкретному арендатору. Subscription —
единственная tenant-owned таблица здесь: ровно одна активная подписка на
арендатора (UniqueConstraint(tenant_id), а не история — см.
docs/BILLING_DESIGN.md §Subscription model)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Feature(enum.StrEnum):
    """«Может ли арендатор использовать X» — булево, не число (см.
    docs/BILLING_DESIGN.md §Feature vs Limit). BASIC_BOOKING — базовая линия:
    истинна на каждом тарифе, ничто в приложении её не проверяет — она
    существует как образец того, как моделируется универсальная фича, и
    задел на будущее, если когда-нибудь появится тариф без неё."""

    BASIC_BOOKING = "basic_booking"
    REMINDERS = "reminders"
    CSV_EXPORT = "csv_export"
    ANALYTICS = "analytics"


class LimitKey(enum.StrEnum):
    """«Сколько X может использовать арендатор» — число или «без ограничений»
    (PlanLimit.value IS NULL), не булево. Сознательно нет MULTI_BRANCH: это
    полностью описывается значением MAX_BRANCHES (см. docs/BILLING_DESIGN.md)."""

    MAX_BRANCHES = "max_branches"
    MAX_BARBERS = "max_barbers"
    MAX_STAFF = "max_staff"
    MAX_SERVICES = "max_services"
    MAX_MONTHLY_APPOINTMENTS = "max_monthly_appointments"


class SubscriptionStatus(enum.StrEnum):
    """Провайдер-независимые статусы — не копия статусов Stripe. Phase 6
    реально присваивает только ACTIVE; остальные существуют как валидные,
    тестируемые состояния для is_effectively_active() (см.
    docs/BILLING_DESIGN.md §Subscription lifecycle) — так же, как
    TenantStatus.SUSPENDED в Phase 5 был определён, но не назначался."""

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Тариф — каталожная сущность платформы, не арендатора: без
    TenantScopedMixin намеренно (см. docs/BILLING_DESIGN.md §Database design)."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )

    features: Mapped[list[PlanFeature]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )
    limits: Mapped[list[PlanLimit]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )


class PlanFeature(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan_features"
    __table_args__ = (
        UniqueConstraint("plan_id", "feature", name="uq_plan_features_plan_id_feature"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature: Mapped[Feature] = mapped_column(
        Enum(Feature, name="billing_feature", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    plan: Mapped[Plan] = relationship(back_populates="features")


class PlanLimit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan_limits"
    __table_args__ = (
        UniqueConstraint("plan_id", "limit_key", name="uq_plan_limits_plan_id_limit_key"),
        CheckConstraint("value IS NULL OR value >= 0", name="non_negative_limit"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    limit_key: Mapped[LimitKey] = mapped_column(
        Enum(LimitKey, name="billing_limit_key", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # NULL = без ограничений (см. docs/BILLING_DESIGN.md §Limit model) —
    # не 0 и не -1, чтобы «нет лимита» нельзя было спутать с «лимит нулевой».
    value: Mapped[int | None] = mapped_column(Integer)

    plan: Mapped[Plan] = relationship(back_populates="limits")


class Subscription(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ровно одна строка на арендатора (UniqueConstraint(tenant_id)) — не
    история изменений. Пока нет реальных платёжных событий, AuditLogEntry
    уже фиксирует ФАКТ смены тарифа/статуса; полноценный журнал подписок —
    задел на будущее (см. docs/BILLING_DESIGN.md).

    current_period_start/end — UTC-aware, для будущего Stripe-цикла
    оплаты; сегодняшний расчёт месячного лимита их не читает (см.
    docs/BILLING_DESIGN.md §Usage model) — намеренно, а не забытая деталь."""

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_subscriptions_tenant_id"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(
            SubscriptionStatus,
            name="subscription_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[Plan] = relationship(lazy="joined")
