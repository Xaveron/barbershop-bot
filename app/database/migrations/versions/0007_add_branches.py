"""Add branches, barber_branches, branch_services, staff_branches;
branch_id on working_schedules/schedule_exceptions/appointments

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-14 00:00:02

"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_BRANCH_NAME = "Основной филиал"


def upgrade() -> None:
    # --- 1. branches -----------------------------------------------------------
    op.create_table(
        "branches",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("maps_url", sa.Text(), nullable=True),
        sa.Column(
            "timezone", sa.String(length=64), nullable=False, server_default="Europe/Chisinau"
        ),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="MDL"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_branches"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_branches_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_branches_tenant_id_name"),
    )
    op.create_index("ix_branches_tenant_id", "branches", ["tenant_id"])
    op.create_index("ix_branches_is_active", "branches", ["is_active"])

    # --- 2. barber_branches / branch_services / staff_branches ------------------
    op.create_table(
        "barber_branches",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("barber_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("branch_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_barber_branches"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_barber_branches_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["barber_id"], ["barbers.id"], name="fk_barber_branches_barber_id_barbers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], name="fk_barber_branches_branch_id_branches",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "barber_id", "branch_id",
            name="uq_barber_branches_tenant_id_barber_id_branch_id",
        ),
    )
    op.create_index("ix_barber_branches_tenant_id", "barber_branches", ["tenant_id"])
    op.create_index("ix_barber_branches_barber_id", "barber_branches", ["barber_id"])
    op.create_index("ix_barber_branches_branch_id", "barber_branches", ["branch_id"])

    op.create_table(
        "branch_services",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("branch_id", sa.Uuid(as_uuid=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_branch_services"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_branch_services_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], name="fk_branch_services_branch_id_branches",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.id"], name="fk_branch_services_service_id_services",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "branch_id", "service_id",
            name="uq_branch_services_tenant_id_branch_id_service_id",
        ),
    )
    op.create_index("ix_branch_services_tenant_id", "branch_services", ["tenant_id"])
    op.create_index("ix_branch_services_branch_id", "branch_services", ["branch_id"])
    op.create_index("ix_branch_services_service_id", "branch_services", ["service_id"])

    op.create_table(
        "staff_branches",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("staff_member_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("branch_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_branches"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_staff_branches_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["staff_member_id"], ["staff_members.id"],
            name="fk_staff_branches_staff_member_id_staff_members", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], name="fk_staff_branches_branch_id_branches",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "staff_member_id", "branch_id",
            name="uq_staff_branches_tenant_id_staff_member_id_branch_id",
        ),
    )
    op.create_index("ix_staff_branches_tenant_id", "staff_branches", ["tenant_id"])
    op.create_index("ix_staff_branches_staff_member_id", "staff_branches", ["staff_member_id"])
    op.create_index("ix_staff_branches_branch_id", "staff_branches", ["branch_id"])

    # --- 3. branch_id на существующих таблицах (сначала nullable) ---------------
    for table in ("working_schedules", "schedule_exceptions", "appointments"):
        op.add_column(table, sa.Column("branch_id", sa.Uuid(as_uuid=True), nullable=True))

    # --- 4. по-арендаторный бэкфилл: один branch по умолчанию на каждого
    # СУЩЕСТВУЮЩЕГО арендатора (а не один глобальный, как в 0004, — там
    # арендатор создавался с нуля, здесь их может быть несколько) ---------------
    conn = op.get_bind()
    branches_table = sa.table(
        "branches",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("tenant_id", sa.Uuid(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("address", sa.Text),
        sa.column("phone", sa.String),
        sa.column("timezone", sa.String),
        sa.column("currency", sa.String),
    )
    barber_branches_table = sa.table(
        "barber_branches",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("tenant_id", sa.Uuid(as_uuid=True)),
        sa.column("barber_id", sa.Uuid(as_uuid=True)),
        sa.column("branch_id", sa.Uuid(as_uuid=True)),
    )
    branch_services_table = sa.table(
        "branch_services",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("tenant_id", sa.Uuid(as_uuid=True)),
        sa.column("branch_id", sa.Uuid(as_uuid=True)),
        sa.column("service_id", sa.Uuid(as_uuid=True)),
    )

    tenants = conn.execute(
        sa.text("SELECT id, shop_address, shop_phone, timezone, currency FROM tenants")
    ).all()

    for tenant in tenants:
        branch_id = uuid.uuid4()
        conn.execute(
            pg_insert(branches_table)
            .values(
                id=branch_id,
                tenant_id=tenant.id,
                name=DEFAULT_BRANCH_NAME,
                address=tenant.shop_address,
                phone=tenant.shop_phone,
                timezone=tenant.timezone,
                currency=tenant.currency,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "name"])
        )

        for table in ("working_schedules", "schedule_exceptions", "appointments"):
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET branch_id = :branch_id "
                    "WHERE tenant_id = :tenant_id AND branch_id IS NULL"
                ).bindparams(branch_id=branch_id, tenant_id=tenant.id)
            )

        barber_ids = (
            conn.execute(
                sa.text("SELECT id FROM barbers WHERE tenant_id = :tenant_id").bindparams(
                    tenant_id=tenant.id
                )
            )
            .scalars()
            .all()
        )
        if barber_ids:
            conn.execute(
                pg_insert(barber_branches_table)
                .values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "tenant_id": tenant.id,
                            "barber_id": bid,
                            "branch_id": branch_id,
                        }
                        for bid in barber_ids
                    ]
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "barber_id", "branch_id"])
            )

        service_ids = (
            conn.execute(
                sa.text("SELECT id FROM services WHERE tenant_id = :tenant_id").bindparams(
                    tenant_id=tenant.id
                )
            )
            .scalars()
            .all()
        )
        if service_ids:
            conn.execute(
                pg_insert(branch_services_table)
                .values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "tenant_id": tenant.id,
                            "branch_id": branch_id,
                            "service_id": sid,
                        }
                        for sid in service_ids
                    ]
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "branch_id", "service_id"])
            )

    # --- 5. NOT NULL + FK + индексы на трёх существующих таблицах ---------------
    op.alter_column("working_schedules", "branch_id", nullable=False)
    op.create_foreign_key(
        "fk_working_schedules_branch_id_branches", "working_schedules", "branches",
        ["branch_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_working_schedules_branch_id", "working_schedules", ["branch_id"])
    op.drop_constraint("uq_working_schedules_barber_id_weekday", "working_schedules", type_="unique")
    op.create_unique_constraint(
        "uq_working_schedules_barber_id_branch_id_weekday", "working_schedules",
        ["barber_id", "branch_id", "weekday"],
    )

    op.alter_column("schedule_exceptions", "branch_id", nullable=False)
    op.create_foreign_key(
        "fk_schedule_exceptions_branch_id_branches", "schedule_exceptions", "branches",
        ["branch_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_schedule_exceptions_branch_id", "schedule_exceptions", ["branch_id"])
    op.drop_index("uq_schedule_exceptions_barber_date", table_name="schedule_exceptions")
    op.create_index(
        "uq_schedule_exceptions_barber_date", "schedule_exceptions",
        ["tenant_id", "branch_id", "barber_id", "exception_date"],
        unique=True, postgresql_where=sa.text("barber_id IS NOT NULL"),
    )
    op.drop_index("uq_schedule_exceptions_global_date", table_name="schedule_exceptions")
    op.create_index(
        "uq_schedule_exceptions_global_date", "schedule_exceptions",
        ["tenant_id", "branch_id", "exception_date"],
        unique=True, postgresql_where=sa.text("barber_id IS NULL"),
    )

    op.alter_column("appointments", "branch_id", nullable=False)
    op.create_foreign_key(
        "fk_appointments_branch_id_branches", "appointments", "branches",
        ["branch_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_appointments_tenant_id_branch_id_starts_at", "appointments",
        ["tenant_id", "branch_id", "starts_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_appointments_tenant_id_branch_id_starts_at", table_name="appointments")
    op.drop_constraint("fk_appointments_branch_id_branches", "appointments", type_="foreignkey")
    op.drop_column("appointments", "branch_id")

    op.drop_index("uq_schedule_exceptions_global_date", table_name="schedule_exceptions")
    op.create_index(
        "uq_schedule_exceptions_global_date", "schedule_exceptions",
        ["tenant_id", "exception_date"], unique=True,
        postgresql_where=sa.text("barber_id IS NULL"),
    )
    op.drop_index("uq_schedule_exceptions_barber_date", table_name="schedule_exceptions")
    op.create_index(
        "uq_schedule_exceptions_barber_date", "schedule_exceptions",
        ["tenant_id", "barber_id", "exception_date"], unique=True,
        postgresql_where=sa.text("barber_id IS NOT NULL"),
    )
    op.drop_index("ix_schedule_exceptions_branch_id", table_name="schedule_exceptions")
    op.drop_constraint(
        "fk_schedule_exceptions_branch_id_branches", "schedule_exceptions", type_="foreignkey"
    )
    op.drop_column("schedule_exceptions", "branch_id")

    op.drop_constraint(
        "uq_working_schedules_barber_id_branch_id_weekday", "working_schedules", type_="unique"
    )
    op.create_unique_constraint(
        "uq_working_schedules_barber_id_weekday", "working_schedules", ["barber_id", "weekday"]
    )
    op.drop_index("ix_working_schedules_branch_id", table_name="working_schedules")
    op.drop_constraint(
        "fk_working_schedules_branch_id_branches", "working_schedules", type_="foreignkey"
    )
    op.drop_column("working_schedules", "branch_id")

    op.drop_table("staff_branches")
    op.drop_table("branch_services")
    op.drop_table("barber_branches")
    op.drop_table("branches")
