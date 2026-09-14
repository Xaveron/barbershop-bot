"""Add audit_log_entries table

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14 00:00:01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("actor_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log_entries"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_audit_log_entries_tenant_id_tenants",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_audit_log_entries_tenant_id", "audit_log_entries", ["tenant_id"])
    op.create_index(
        "ix_audit_log_entries_tenant_id_created_at",
        "audit_log_entries",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_entries_tenant_id_created_at", table_name="audit_log_entries")
    op.drop_index("ix_audit_log_entries_tenant_id", table_name="audit_log_entries")
    op.drop_table("audit_log_entries")
