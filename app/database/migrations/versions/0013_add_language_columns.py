"""Add Tenant.default_language and StaffMember.language

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-16 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- tenants.default_language -------------------------------------------
    # Тот же паттерн, что и tenant_id в миграции 0004: добавить nullable ->
    # забэкфиллить -> NOT NULL. Значение бэкфилла — НЕ выдуманная константа:
    # это settings.default_language, прочитанный из фактического окружения
    # ЭТОГО запуска миграции (get_settings(), как уже делает миграция 0004
    # для settings.timezone/settings.default_currency при заполнении первой
    # строки tenants). На момент написания в .env / Settings — DEFAULT_LANGUAGE=ru
    # (Settings.default_language default тоже "ru"), поэтому существующие
    # арендаторы получают "ru" — их текущий эффективный язык не меняется
    # (см. Phase 9E §3/§26.3 финального отчёта).
    op.add_column(
        "tenants",
        sa.Column("default_language", sa.String(length=8), nullable=True),
    )
    settings = get_settings()
    tenants = sa.table("tenants", sa.column("default_language", sa.String))
    op.execute(
        tenants.update()
        .where(tenants.c.default_language.is_(None))
        .values(default_language=settings.default_language)
    )
    op.alter_column("tenants", "default_language", nullable=False)

    # --- staff_members.language ----------------------------------------------
    # Nullable, без бэкфилла: NULL = наследует Tenant.default_language во время
    # выполнения (см. app/services/locale.py) — придумывать значение для уже
    # существующих сотрудников не нужно и не требуется спецификацией фазы.
    op.add_column(
        "staff_members",
        sa.Column("language", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("staff_members", "language")
    op.drop_column("tenants", "default_language")
