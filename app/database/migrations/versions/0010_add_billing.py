"""Add billing domain: plans, plan_features, plan_limits, subscriptions;
seed Free/Pro/Legacy plans and backfill Legacy subscriptions for existing tenants

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-15 00:00:01

"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FEATURE_VALUES = ("basic_booking", "reminders", "csv_export", "analytics")
LIMIT_KEY_VALUES = (
    "max_branches",
    "max_barbers",
    "max_staff",
    "max_services",
    "max_monthly_appointments",
)
SUBSCRIPTION_STATUS_VALUES = ("trialing", "active", "past_due", "canceled", "expired")

# Каталог тарифов — данные миграции, а не хардкод в коде приложения (см.
# docs/BILLING_DESIGN.md §Каталог тарифов): изменить лимит/фичу тарифа в
# будущем — это UPDATE строки, а не деплой нового кода. Значение None у
# лимита означает "без ограничений".
PLAN_SEEDS: dict[str, dict[str, object]] = {
    "free": {
        "name": "Free",
        "description": "Стартовый тариф для новых арендаторов.",
        "is_active": True,
        "features": ("basic_booking", "reminders"),
        "limits": {
            "max_branches": 1,
            "max_barbers": 2,
            "max_staff": 3,
            "max_services": 10,
            "max_monthly_appointments": 100,
        },
    },
    "pro": {
        "name": "Pro",
        "description": "Без ограничений на объём, со всеми функциями.",
        "is_active": True,
        "features": ("basic_booking", "reminders", "csv_export", "analytics"),
        "limits": {
            "max_branches": None,
            "max_barbers": None,
            "max_staff": None,
            "max_services": None,
            "max_monthly_appointments": None,
        },
    },
    "legacy": {
        # Служебный тариф: не предлагается новым арендаторам (is_active=False),
        # используется только бэкфиллом ниже — см. docs/BILLING_DESIGN.md
        # §Existing-tenant backfill.
        "name": "Legacy",
        "description": (
            "Служебный тариф для арендаторов, созданных до появления биллинга "
            "(Phase 6) — без ограничений, чтобы не сломать уже работающий бизнес."
        ),
        "is_active": False,
        "features": ("basic_booking", "reminders", "csv_export", "analytics"),
        "limits": {
            "max_branches": None,
            "max_barbers": None,
            "max_staff": None,
            "max_services": None,
            "max_monthly_appointments": None,
        },
    },
}


def upgrade() -> None:
    # Все три enum'а используются только в НОВЫХ таблицах ниже — op.create_table
    # сам создаёт нужный enum-тип по ходу DDL (см. миграцию 0005). Отдельный
    # явный .create(checkfirst=True) нужен только для op.add_column на уже
    # существующей таблице (см. миграцию 0009) — здесь он лишний и приводит
    # к DuplicateObjectError, когда op.create_table пытается создать тот же тип.
    feature_enum = sa.Enum(*FEATURE_VALUES, name="billing_feature")
    limit_key_enum = sa.Enum(*LIMIT_KEY_VALUES, name="billing_limit_key")
    subscription_status_enum = sa.Enum(*SUBSCRIPTION_STATUS_VALUES, name="subscription_status")

    # --- 1. plans: глобальный каталог, без tenant_id (тариф принадлежит
    # платформе, а не арендатору) ------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint("code", name="uq_plans_code"),
    )

    # --- 2. plan_features --------------------------------------------------
    op.create_table(
        "plan_features",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("feature", feature_enum, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_features"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name="fk_plan_features_plan_id_plans",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("plan_id", "feature", name="uq_plan_features_plan_id_feature"),
    )
    op.create_index("ix_plan_features_plan_id", "plan_features", ["plan_id"])

    # --- 3. plan_limits ------------------------------------------------------
    op.create_table(
        "plan_limits",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("limit_key", limit_key_enum, nullable=False),
        # NULL = без ограничений (см. app/database/models/billing.py::PlanLimit).
        sa.Column("value", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_limits"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name="fk_plan_limits_plan_id_plans",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("plan_id", "limit_key", name="uq_plan_limits_plan_id_limit_key"),
        sa.CheckConstraint(
            "value IS NULL OR value >= 0", name="ck_plan_limits_non_negative_limit"
        ),
    )
    op.create_index("ix_plan_limits_plan_id", "plan_limits", ["plan_id"])

    # --- 4. subscriptions: tenant-owned, ровно одна строка на арендатора -----
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", subscription_status_enum, nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_subscriptions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name="fk_subscriptions_plan_id_plans",
            ondelete="RESTRICT",
        ),
        # Ровно одна подписка на арендатора — не история (см.
        # docs/BILLING_DESIGN.md §Subscription model).
        sa.UniqueConstraint("tenant_id", name="uq_subscriptions_tenant_id"),
    )
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])

    # --- 5. Данные: каталог тарифов ------------------------------------------
    conn = op.get_bind()

    plans_table = sa.table(
        "plans",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_active", sa.Boolean),
    )
    # asyncpg требует явный каст к native enum-типу Postgres для этих колонок
    # (тот же приём, что и в 0005/0009 — обычный VARCHAR-бинд не пройдёт).
    plan_features_table = sa.table(
        "plan_features",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("plan_id", sa.Uuid(as_uuid=True)),
        sa.column("feature", feature_enum),
    )
    plan_limits_table = sa.table(
        "plan_limits",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("plan_id", sa.Uuid(as_uuid=True)),
        sa.column("limit_key", limit_key_enum),
        sa.column("value", sa.Integer),
    )
    subscriptions_table = sa.table(
        "subscriptions",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("tenant_id", sa.Uuid(as_uuid=True)),
        sa.column("plan_id", sa.Uuid(as_uuid=True)),
        sa.column("status", subscription_status_enum),
        sa.column("current_period_start", sa.DateTime(timezone=True)),
    )

    plan_ids: dict[str, uuid.UUID] = {code: uuid.uuid4() for code in PLAN_SEEDS}

    conn.execute(
        pg_insert(plans_table)
        .values(
            [
                {
                    "id": plan_ids[code],
                    "code": code,
                    "name": seed["name"],
                    "description": seed["description"],
                    "is_active": seed["is_active"],
                }
                for code, seed in PLAN_SEEDS.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["code"])
    )

    feature_rows = [
        {"id": uuid.uuid4(), "plan_id": plan_ids[code], "feature": feature}
        for code, seed in PLAN_SEEDS.items()
        for feature in seed["features"]
    ]
    conn.execute(
        pg_insert(plan_features_table)
        .values(feature_rows)
        .on_conflict_do_nothing(index_elements=["plan_id", "feature"])
    )

    limit_rows = [
        {"id": uuid.uuid4(), "plan_id": plan_ids[code], "limit_key": limit_key, "value": value}
        for code, seed in PLAN_SEEDS.items()
        for limit_key, value in seed["limits"].items()
    ]
    conn.execute(
        pg_insert(plan_limits_table)
        .values(limit_rows)
        .on_conflict_do_nothing(index_elements=["plan_id", "limit_key"])
    )

    # --- 6. Данные: подписка Legacy для каждого существующего арендатора ------
    # Legacy — без ограничений: у арендатора, созданного до Phase 6, не может
    # появиться новый лимит, который он тут же нарушает (см.
    # docs/BILLING_DESIGN.md §Existing-tenant backfill). Не Free: Free — тариф
    # по умолчанию только для арендаторов, создаваемых С ЭТОГО МОМЕНТА
    # (TenantOnboardingService.create_tenant), а не ретроактивный дефолт.
    tenant_ids = conn.execute(sa.text("SELECT id FROM tenants")).scalars().all()
    if tenant_ids:
        legacy_plan_id = plan_ids["legacy"]
        period_start = datetime.now(UTC)
        conn.execute(
            pg_insert(subscriptions_table)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "plan_id": legacy_plan_id,
                        "status": "active",
                        "current_period_start": period_start,
                    }
                    for tenant_id in tenant_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["tenant_id"])
        )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_tenant_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_plan_limits_plan_id", table_name="plan_limits")
    op.drop_table("plan_limits")
    op.drop_index("ix_plan_features_plan_id", table_name="plan_features")
    op.drop_table("plan_features")
    op.drop_table("plans")
    sa.Enum(name="subscription_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="billing_limit_key").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="billing_feature").drop(op.get_bind(), checkfirst=True)
