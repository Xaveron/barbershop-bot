"""Add staff_members table and RBAC roles

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14 00:00:00

"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_VALUES = ("tenant_owner", "tenant_admin", "manager", "receptionist", "barber")


def upgrade() -> None:
    staff_role = sa.Enum(*ROLE_VALUES, name="staff_role")

    op.create_table(
        "staff_members",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("role", staff_role, nullable=False),
        sa.Column("barber_id", sa.Uuid(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_staff_members"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_staff_members_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["barber_id"], ["barbers.id"], name="fk_staff_members_barber_id_barbers",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id", "telegram_id", name="uq_staff_members_tenant_id_telegram_id"
        ),
    )
    op.create_index("ix_staff_members_tenant_id", "staff_members", ["tenant_id"])
    op.create_index("ix_staff_members_telegram_id", "staff_members", ["telegram_id"])

    # --- Данные: существующие ADMIN_ID -> StaffMember --------------------------
    # Арендатора берём из уже существующей строки (0004 её создала), а не
    # заново выводя UUID из Settings, как это делала 0004 для другой цели.
    admin_ids = get_settings().admin_ids
    if admin_ids:
        conn = op.get_bind()
        tenant_id = conn.execute(
            sa.text("SELECT id FROM tenants ORDER BY created_at LIMIT 1")
        ).scalar_one()

        staff_table = sa.table(
            "staff_members",
            sa.column("id", sa.Uuid(as_uuid=True)),
            sa.column("tenant_id", sa.Uuid(as_uuid=True)),
            sa.column("telegram_id", sa.BigInteger),
            # asyncpg требует явный каст к native enum-типу Postgres — обычный
            # VARCHAR-бинд, который сгенерировал бы sa.String(), эту DDL не
            # пройдёт (DatatypeMismatchError).
            sa.column("role", staff_role),
            sa.column("is_active", sa.Boolean),
        )
        rows = [
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "telegram_id": telegram_id,
                # Единственный доступный сигнал, кто из ADMIN_ID — владелец:
                # первый перечисленный (Settings.admin_ids не различает их
                # иначе). Если порядок в ADMIN_ID не отражает реального
                # владельца — поправьте вручную после миграции.
                "role": "tenant_owner" if index == 0 else "tenant_admin",
                "is_active": True,
            }
            for index, telegram_id in enumerate(admin_ids)
        ]
        stmt = pg_insert(staff_table).values(rows).on_conflict_do_nothing(
            index_elements=["tenant_id", "telegram_id"]
        )
        conn.execute(stmt)


def downgrade() -> None:
    op.drop_index("ix_staff_members_telegram_id", table_name="staff_members")
    op.drop_index("ix_staff_members_tenant_id", table_name="staff_members")
    op.drop_table("staff_members")
    sa.Enum(name="staff_role").drop(op.get_bind(), checkfirst=True)
