from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.appointment import Appointment
    from app.database.models.schedule import ScheduleException, WorkingSchedule


class Barber(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Мастер барбершопа."""

    __tablename__ = "barbers"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=100, server_default=text("100"), nullable=False
    )

    working_schedules: Mapped[list[WorkingSchedule]] = relationship(
        back_populates="barber",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    schedule_exceptions: Mapped[list[ScheduleException]] = relationship(
        back_populates="barber",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    appointments: Mapped[list[Appointment]] = relationship(back_populates="barber")
