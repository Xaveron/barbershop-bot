"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # btree_gist нужен для EXCLUDE-констрейнта по (uuid =, tstzrange &&).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("language_code", sa.String(length=8), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "barbers",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_barbers"),
        sa.UniqueConstraint("telegram_id", name="uq_barbers_telegram_id"),
    )
    op.create_index("ix_barbers_is_active", "barbers", ["is_active"])

    op.create_table(
        "services",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="MDL"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_services"),
        sa.UniqueConstraint("name", name="uq_services_name"),
        sa.CheckConstraint(
            "duration_minutes > 0 AND duration_minutes <= 480",
            name="ck_services_duration_range",
        ),
        sa.CheckConstraint("price >= 0", name="ck_services_price_non_negative"),
    )
    op.create_index("ix_services_is_active", "services", ["is_active"])

    op.create_table(
        "working_schedules",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("barber_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["barber_id"],
            ["barbers.id"],
            name="fk_working_schedules_barber_id_barbers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_working_schedules"),
        sa.UniqueConstraint("barber_id", "weekday", name="uq_working_schedules_barber_id_weekday"),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_working_schedules_weekday_range"),
        sa.CheckConstraint("end_time > start_time", name="ck_working_schedules_valid_time_range"),
    )
    op.create_index("ix_working_schedules_barber_id", "working_schedules", ["barber_id"])

    op.create_table(
        "schedule_exceptions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("barber_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("exception_date", sa.Date(), nullable=False),
        sa.Column("is_day_off", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["barber_id"],
            ["barbers.id"],
            name="fk_schedule_exceptions_barber_id_barbers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_schedule_exceptions"),
        sa.CheckConstraint(
            "(is_day_off = true AND start_time IS NULL AND end_time IS NULL)"
            " OR (is_day_off = false AND start_time IS NOT NULL AND end_time IS NOT NULL"
            " AND end_time > start_time)",
            name="ck_schedule_exceptions_valid_exception_window",
        ),
    )
    op.create_index("ix_schedule_exceptions_exception_date", "schedule_exceptions", ["exception_date"])
    op.create_index(
        "uq_schedule_exceptions_barber_date",
        "schedule_exceptions",
        ["barber_id", "exception_date"],
        unique=True,
        postgresql_where=sa.text("barber_id IS NOT NULL"),
    )
    op.create_index(
        "uq_schedule_exceptions_global_date",
        "schedule_exceptions",
        ["exception_date"],
        unique=True,
        postgresql_where=sa.text("barber_id IS NULL"),
    )

    appointment_status = sa.Enum(
        "confirmed", "cancelled", "completed", name="appointment_status"
    )
    cancelled_by = sa.Enum("client", "admin", "system", name="cancelled_by")

    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("barber_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("service_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", appointment_status, nullable=False, server_default="confirmed"),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="MDL"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", cancelled_by, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_appointments_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["barber_id"],
            ["barbers.id"],
            name="fk_appointments_barber_id_barbers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name="fk_appointments_service_id_services",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_appointments"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_appointments_valid_time_range"),
        sa.CheckConstraint("duration_minutes > 0", name="ck_appointments_positive_duration"),
        sa.CheckConstraint("price >= 0", name="ck_appointments_price_non_negative"),
    )
    op.create_index("ix_appointments_starts_at", "appointments", ["starts_at"])
    op.create_index("ix_appointments_barber_id_starts_at", "appointments", ["barber_id", "starts_at"])
    op.create_index("ix_appointments_user_id_starts_at", "appointments", ["user_id", "starts_at"])
    op.create_index("ix_appointments_status_starts_at", "appointments", ["status", "starts_at"])

    # Главная защита от двойного бронирования: пересечение интервалов
    # одного барбера невозможно среди подтверждённых записей.
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

    notification_kind = sa.Enum("reminder_24h", "reminder_2h", name="notification_kind")
    notification_status = sa.Enum("pending", "sent", "failed", name="notification_status")

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("appointment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", notification_kind, nullable=False),
        sa.Column("status", notification_status, nullable=False, server_default="pending"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name="fk_notifications_appointment_id_appointments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.UniqueConstraint("appointment_id", "kind", name="uq_notifications_appointment_id_kind"),
    )
    op.create_index(
        "ix_notifications_status_scheduled_for", "notifications", ["status", "scheduled_for"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_status_scheduled_for", table_name="notifications")
    op.drop_table("notifications")
    sa.Enum(name="notification_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notification_kind").drop(op.get_bind(), checkfirst=True)

    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS excl_appointments_barber_no_overlap")
    op.drop_index("ix_appointments_status_starts_at", table_name="appointments")
    op.drop_index("ix_appointments_user_id_starts_at", table_name="appointments")
    op.drop_index("ix_appointments_barber_id_starts_at", table_name="appointments")
    op.drop_index("ix_appointments_starts_at", table_name="appointments")
    op.drop_table("appointments")
    sa.Enum(name="cancelled_by").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="appointment_status").drop(op.get_bind(), checkfirst=True)

    op.drop_index("uq_schedule_exceptions_global_date", table_name="schedule_exceptions")
    op.drop_index("uq_schedule_exceptions_barber_date", table_name="schedule_exceptions")
    op.drop_index("ix_schedule_exceptions_exception_date", table_name="schedule_exceptions")
    op.drop_table("schedule_exceptions")

    op.drop_index("ix_working_schedules_barber_id", table_name="working_schedules")
    op.drop_table("working_schedules")

    op.drop_index("ix_services_is_active", table_name="services")
    op.drop_table("services")

    op.drop_index("ix_barbers_is_active", table_name="barbers")
    op.drop_table("barbers")

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
