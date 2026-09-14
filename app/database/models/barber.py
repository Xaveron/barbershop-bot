from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.appointment import Appointment
    from app.database.models.schedule import ScheduleException, WorkingSchedule


class Barber(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Мастер барбершопа."""

    __tablename__ = "barbers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "telegram_id", name="uq_barbers_tenant_id_telegram_id"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
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


class BarberService(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Барбер предоставляет услугу. Отсутствие строки для (barber_id, service_id)
    означает «предоставляет» (тот же opt-out паттерн, что BranchService, — см.
    docs/STAFF_SERVICE_BRANCH_DESIGN.md): любой барбер сегодня может выполнить
    любую услугу, и бэкфилл строк по всем существующим парам сломал бы это на
    новых барберах/услугах, требуя ручной настройки каждой комбинации. Строка
    с is_active=false — точечный отказ конкретного барбера от конкретной услуги."""

    __tablename__ = "barber_services"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "barber_id", "service_id",
            name="uq_barber_services_tenant_id_barber_id_service_id",
        ),
    )

    barber_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("barbers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
