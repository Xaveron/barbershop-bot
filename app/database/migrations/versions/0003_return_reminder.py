"""Add return_reminder notification kind

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-14 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS 'return_reminder'")


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значений enum напрямую.
    # Для отката: пересоздать тип без 'return_reminder' вручную.
    pass
