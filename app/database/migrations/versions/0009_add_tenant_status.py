"""Add Tenant.status lifecycle (onboarding/active/suspended) and enforce
at most one tenant_owner per tenant

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-15 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_STATUS_VALUES = ("onboarding", "active", "suspended")


def upgrade() -> None:
    tenant_status = sa.Enum(*TENANT_STATUS_VALUES, name="tenant_status")
    # В отличие от op.create_table (сама создаёт нужные enum-типы по ходу DDL,
    # см. миграцию 0005), op.add_column на уже существующей таблице этого не
    # делает — тип нужно создать явно, до ALTER TABLE.
    tenant_status.create(op.get_bind(), checkfirst=True)

    # server_default='active' здесь — только чтобы одним ALTER-ом безопасно
    # забэкфиллить СУЩЕСТВУЮЩИЕ строки (они уже реально обслуживают клиентов,
    # см. docs/TENANT_ONBOARDING_DESIGN.md) без отдельного UPDATE по всей
    # таблице. Дефолт сразу снимается: дальше статус — обязательное явное
    # значение на уровне приложения (Tenant.status default=ONBOARDING в
    # Python), а не молчаливый server_default, который иначе одинаково
    # применился бы и к новым арендаторам.
    op.add_column(
        "tenants",
        sa.Column("status", tenant_status, nullable=False, server_default="active"),
    )
    op.alter_column("tenants", "status", server_default=None)

    # Не более одного tenant_owner на арендатора — гарантия на уровне БД
    # (частичный уникальный индекс), а не только питоновской проверки перед
    # INSERT-ом, которую гонка двух одновременных /start могла бы обойти.
    op.create_index(
        "uq_staff_members_tenant_id_owner",
        "staff_members",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("role = 'tenant_owner'"),
    )


def downgrade() -> None:
    op.drop_index("uq_staff_members_tenant_id_owner", table_name="staff_members")
    op.drop_column("tenants", "status")
    sa.Enum(name="tenant_status").drop(op.get_bind(), checkfirst=True)
