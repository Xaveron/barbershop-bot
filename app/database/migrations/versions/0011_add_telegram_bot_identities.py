"""Add telegram_bot_identities: maps a Telegram bot identity to a tenant

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-15 00:00:02

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ровно один арендатор на bot (глобальный UniqueConstraint на
    # telegram_bot_id, НЕ (tenant_id, telegram_bot_id)) — арендатор может
    # иметь несколько ботов, но не наоборот (см.
    # docs/BOT_IDENTITY_ARCHITECTURE.md). Никакого бэкфилла: существующие
    # арендаторы не получают угаданную привязку к боту — см.
    # app/register_bot.py для явного, контролируемого провижининга.
    op.create_table(
        "telegram_bot_identities",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("telegram_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_bot_identities"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_telegram_bot_identities_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "telegram_bot_id", name="uq_telegram_bot_identities_telegram_bot_id"
        ),
    )
    op.create_index(
        "ix_telegram_bot_identities_tenant_id", "telegram_bot_identities", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_bot_identities_tenant_id", table_name="telegram_bot_identities")
    op.drop_table("telegram_bot_identities")
