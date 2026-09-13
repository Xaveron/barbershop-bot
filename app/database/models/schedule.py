from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import time as time_type
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.barber import Barber


class WorkingSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Регулярный недельный график барбера. Время локальное (TIMEZONE)."""

    __tablename__ = "working_schedules"
    __table_args__ = (
        UniqueConstraint("barber_id", "weekday", name="uq_working_schedules_barber_id_weekday"),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="valid_time_range"),
    )

    barber_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("barbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 = понедельник
    start_time: Mapped[time_type] = mapped_column(Time, nullable=False)
    end_time: Mapped[time_type] = mapped_column(Time, nullable=False)

    barber: Mapped[Barber] = relationship(back_populates="working_schedules")


class ScheduleException(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Исключение из графика на конкретную дату.

    barber_id = NULL означает исключение для всего барбершопа
    (например, государственный праздник).
    """

    __tablename__ = "schedule_exceptions"
    __table_args__ = (
        CheckConstraint(
            "(is_day_off = true AND start_time IS NULL AND end_time IS NULL)"
            " OR (is_day_off = false AND start_time IS NOT NULL AND end_time IS NOT NULL"
            " AND end_time > start_time)",
            name="valid_exception_window",
        ),
        Index(
            "uq_schedule_exceptions_barber_date",
            "barber_id",
            "exception_date",
            unique=True,
            postgresql_where="barber_id IS NOT NULL",
        ),
        Index(
            "uq_schedule_exceptions_global_date",
            "exception_date",
            unique=True,
            postgresql_where="barber_id IS NULL",
        ),
    )

    barber_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("barbers.id", ondelete="CASCADE"),
    )
    exception_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    is_day_off: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    start_time: Mapped[time_type | None] = mapped_column(Time)
    end_time: Mapped[time_type | None] = mapped_column(Time)
    reason: Mapped[str | None] = mapped_column(String(255))

    barber: Mapped[Barber | None] = relationship(back_populates="schedule_exceptions")

    @property
    def is_global(self) -> bool:
        return self.barber_id is None
