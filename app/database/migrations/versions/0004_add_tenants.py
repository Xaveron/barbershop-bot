"""Add tenants and tenant_id on all tenant-owned tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-14 00:00:00

"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TENANT_ID = uuid.uuid4()

# Таблицы, принадлежащие арендатору (notifications не входит — она достижима
# только через appointment_id, который уже привязан к арендатору).
TENANT_OWNED_TABLES = (
    "users",
    "barbers",
    "services",
    "working_schedules",
    "schedule_exceptions",
    "appointments",
)


def upgrade() -> None:
    # --- 1. tenants ------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column(
            "timezone", sa.String(length=64), nullable=False, server_default="Europe/Chisinau"
        ),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="MDL"),
        sa.Column("shop_name", sa.String(length=255), nullable=True),
        sa.Column("shop_address", sa.Text(), nullable=True),
        sa.Column("shop_phone", sa.String(length=32), nullable=True),
        sa.Column("shop_maps_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    # Единственный арендатор Phase 1, из текущих env/.env — бот продолжает
    # вести себя так же, как и до миграции (Settings остаётся источником
    # истины для бизнес-правил, эти колонки — задел на будущую фазу).
    settings = get_settings()
    tenants_table = sa.table(
        "tenants",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("timezone", sa.String),
        sa.column("currency", sa.String),
        sa.column("shop_name", sa.String),
        sa.column("shop_address", sa.Text),
        sa.column("shop_phone", sa.String),
        sa.column("shop_maps_url", sa.Text),
    )
    op.bulk_insert(
        tenants_table,
        [
            {
                "id": DEFAULT_TENANT_ID,
                "name": settings.shop_name or "Default Tenant",
                "slug": "default",
                "timezone": settings.timezone,
                "currency": settings.default_currency,
                "shop_name": settings.shop_name or None,
                "shop_address": settings.shop_address or None,
                "shop_phone": settings.shop_phone or None,
                "shop_maps_url": settings.shop_maps_url or None,
            }
        ],
    )

    # --- 2. tenant_id на каждой принадлежащей арендатору таблице ----------------
    # Безопасный паттерн для живой таблицы: добавить nullable -> заполнить ->
    # NOT NULL -> FK -> индекс.
    for table in TENANT_OWNED_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=True))
        op.execute(
            sa.text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE tenant_id IS NULL").bindparams(
                tenant_id=DEFAULT_TENANT_ID
            )
        )
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_tenant_id_tenants",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # --- 3. глобальная уникальность -> уникальность в пределах арендатора -------
    op.drop_constraint("uq_services_name", "services", type_="unique")
    op.create_unique_constraint("uq_services_tenant_id_name", "services", ["tenant_id", "name"])

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.create_unique_constraint(
        "uq_users_tenant_id_telegram_id", "users", ["tenant_id", "telegram_id"]
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    op.drop_constraint("uq_barbers_telegram_id", "barbers", type_="unique")
    op.create_unique_constraint(
        "uq_barbers_tenant_id_telegram_id", "barbers", ["tenant_id", "telegram_id"]
    )

    # --- 4. частичные уникальные индексы schedule_exceptions включают tenant_id
    op.drop_index("uq_schedule_exceptions_barber_date", table_name="schedule_exceptions")
    op.create_index(
        "uq_schedule_exceptions_barber_date",
        "schedule_exceptions",
        ["tenant_id", "barber_id", "exception_date"],
        unique=True,
        postgresql_where=sa.text("barber_id IS NOT NULL"),
    )
    op.drop_index("uq_schedule_exceptions_global_date", table_name="schedule_exceptions")
    op.create_index(
        "uq_schedule_exceptions_global_date",
        "schedule_exceptions",
        ["tenant_id", "exception_date"],
        unique=True,
        postgresql_where=sa.text("barber_id IS NULL"),
    )

    # --- 5. appointments: составной индекс для прямой фильтрации по арендатору --
    op.create_index(
        "ix_appointments_tenant_id_starts_at", "appointments", ["tenant_id", "starts_at"]
    )
    # excl_appointments_barber_no_overlap намеренно не трогаем: barber_id уже
    # однозначно определяет арендатора через FK.


def downgrade() -> None:
    op.drop_index("ix_appointments_tenant_id_starts_at", table_name="appointments")

    op.drop_index("uq_schedule_exceptions_global_date", table_name="schedule_exceptions")
    op.create_index(
        "uq_schedule_exceptions_global_date",
        "schedule_exceptions",
        ["exception_date"],
        unique=True,
        postgresql_where=sa.text("barber_id IS NULL"),
    )
    op.drop_index("uq_schedule_exceptions_barber_date", table_name="schedule_exceptions")
    op.create_index(
        "uq_schedule_exceptions_barber_date",
        "schedule_exceptions",
        ["barber_id", "exception_date"],
        unique=True,
        postgresql_where=sa.text("barber_id IS NOT NULL"),
    )

    op.drop_constraint("uq_barbers_tenant_id_telegram_id", "barbers", type_="unique")
    op.create_unique_constraint("uq_barbers_telegram_id", "barbers", ["telegram_id"])

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_constraint("uq_users_tenant_id_telegram_id", "users", type_="unique")
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.drop_constraint("uq_services_tenant_id_name", "services", type_="unique")
    op.create_unique_constraint("uq_services_name", "services", ["name"])

    for table in reversed(TENANT_OWNED_TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id_tenants", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    op.drop_table("tenants")
