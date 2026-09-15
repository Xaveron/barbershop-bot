"""Add platform_operators; make audit_log_entries.tenant_id nullable

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-15 00:00:03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORM_ROLE_VALUES = ("platform_admin",)


def upgrade() -> None:
    # Платформенная идентичность — глобальный каталог, без tenant_id (см.
    # docs/PLATFORM_CONTROL_PLANE.md §Platform identity). Enum создаётся
    # неявно через op.create_table (см. миграцию 0005) — явный
    # .create(checkfirst=True) здесь не нужен и создал бы DuplicateObjectError
    # (тот же урок, что миграция 0010 уже усвоила).
    platform_role = sa.Enum(*PLATFORM_ROLE_VALUES, name="platform_role")

    op.create_table(
        "platform_operators",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", platform_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_operators"),
        sa.UniqueConstraint(
            "telegram_user_id", name="uq_platform_operators_telegram_user_id"
        ),
    )

    # Платформенные события (создание/деактивация PlatformOperator) не
    # относятся ни к одному арендатору — минимальное совместимое расширение
    # существующей таблицы вместо второго журнала (см. §18/§20).
    op.alter_column("audit_log_entries", "tenant_id", nullable=True)


def downgrade() -> None:
    # Платформенные записи (tenant_id IS NULL) не существовали до 0012 и не
    # представимы в старой NOT NULL схеме — при откате они неизбежно
    # теряются (сознательный выбор, не обход ошибки: см.
    # docs/PLATFORM_CONTROL_PLANE.md §Migration).
    op.execute("DELETE FROM audit_log_entries WHERE tenant_id IS NULL")
    op.alter_column("audit_log_entries", "tenant_id", nullable=False)
    op.drop_table("platform_operators")
    sa.Enum(name="platform_role").drop(op.get_bind(), checkfirst=True)
