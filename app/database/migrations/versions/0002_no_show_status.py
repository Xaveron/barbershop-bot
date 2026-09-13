"""Add no_show appointment status

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-02 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL 12+ разрешает ADD VALUE внутри транзакции,
    # если новое значение не используется в этой же транзакции.
    op.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'no_show'")


def downgrade() -> None:
    # Значение enum в PostgreSQL удалить нельзя — пересоздаём тип без 'no_show'.
    op.execute("UPDATE appointments SET status = 'completed' WHERE status = 'no_show'")
    # EXCLUDE-констрейнт ссылается на старый тип в своём WHERE — пересоздаём его.
    op.execute("ALTER TABLE appointments DROP CONSTRAINT excl_appointments_barber_no_overlap")
    op.execute("ALTER TYPE appointment_status RENAME TO appointment_status_old")
    op.execute("CREATE TYPE appointment_status AS ENUM ('confirmed', 'cancelled', 'completed')")
    op.execute("ALTER TABLE appointments ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE appointments ALTER COLUMN status TYPE appointment_status "
        "USING status::text::appointment_status"
    )
    op.execute("ALTER TABLE appointments ALTER COLUMN status SET DEFAULT 'confirmed'")
    op.execute("DROP TYPE appointment_status_old")
    op.execute(
        """
        ALTER TABLE appointments
        ADD CONSTRAINT excl_appointments_barber_no_overlap
        EXCLUDE USING gist (
            barber_id WITH =,
            tstzrange(starts_at, ends_at, '[)') WITH &&
        )
        WHERE (status = 'confirmed'::appointment_status)
        """
    )
