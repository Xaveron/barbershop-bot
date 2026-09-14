"""Add barber_services (barber provides service, opt-out semantics)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-14 00:00:03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Отсутствие строки для (barber_id, service_id) означает «барбер
    # предоставляет услугу» (тот же opt-out паттерн, что branch_services) —
    # поэтому таблица создаётся пустой, бэкфилл не нужен: поведение не
    # меняется ни для одного существующего барбера/услуги (см.
    # docs/STAFF_SERVICE_BRANCH_DESIGN.md).
    op.create_table(
        "barber_services",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("barber_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("service_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_barber_services"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_barber_services_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["barber_id"], ["barbers.id"], name="fk_barber_services_barber_id_barbers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.id"], name="fk_barber_services_service_id_services",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "barber_id", "service_id",
            name="uq_barber_services_tenant_id_barber_id_service_id",
        ),
    )
    op.create_index("ix_barber_services_tenant_id", "barber_services", ["tenant_id"])
    op.create_index("ix_barber_services_barber_id", "barber_services", ["barber_id"])
    op.create_index("ix_barber_services_service_id", "barber_services", ["service_id"])


def downgrade() -> None:
    op.drop_table("barber_services")
