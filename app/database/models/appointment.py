from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.barber import Barber
    from app.database.models.notification import Notification
    from app.database.models.service import Service
    from app.database.models.user import User


class AppointmentStatus(enum.StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    # Клиент не пришёл: слот освобождать поздно, но в статистику он попадает отдельно.
    NO_SHOW = "no_show"


class CancelledBy(enum.StrEnum):
    CLIENT = "client"
    ADMIN = "admin"
    SYSTEM = "system"


ACTIVE_STATUSES: tuple[AppointmentStatus, ...] = (
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.COMPLETED,
)


class Appointment(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Запись клиента к барберу.

    Время хранится в UTC (timestamptz).

    Двойная запись предотвращается на уровне PostgreSQL EXCLUDE-констрейнтом
    (см. миграцию 0001): пересечение интервалов [starts_at, ends_at) для одного
    барбера невозможно, пока статус = 'confirmed'. Констрейнт создаётся сырым
    SQL, поэтому в metadata его нет — это осознанное решение ради совместимости.
    Констрейнт ключуется по barber_id без tenant_id/branch_id: barber_id — FK
    ровно на одного арендатора и не может физически быть в двух местах
    одновременно, так что он уже однозначно и достаточно разделяет и
    арендаторов, и филиалы. branch_id на записи — информационный/для
    фильтрации, НЕ часть защиты от двойного бронирования (см.
    docs/BRANCHES_DESIGN.md) — иначе того же барбера можно было бы записать
    одновременно в два филиала.
    """

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="valid_time_range"),
        CheckConstraint("duration_minutes > 0", name="positive_duration"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        Index("ix_appointments_barber_id_starts_at", "barber_id", "starts_at"),
        Index("ix_appointments_user_id_starts_at", "user_id", "starts_at"),
        Index("ix_appointments_status_starts_at", "status", "starts_at"),
        Index("ix_appointments_tenant_id_starts_at", "tenant_id", "starts_at"),
        Index(
            "ix_appointments_tenant_id_branch_id_starts_at", "tenant_id", "branch_id", "starts_at"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
    )
    barber_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("barbers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("services.id", ondelete="RESTRICT"),
        nullable=False,
    )

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            name="appointment_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=AppointmentStatus.CONFIRMED,
        server_default=AppointmentStatus.CONFIRMED.value,
        nullable=False,
    )

    # Снимок стоимости и длительности на момент записи: изменение прайса
    # не должно менять историю уже созданных записей.
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), default="MDL", server_default="MDL", nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    comment: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[CancelledBy | None] = mapped_column(
        Enum(
            CancelledBy,
            name="cancelled_by",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )

    user: Mapped[User] = relationship(back_populates="appointments", lazy="joined")
    barber: Mapped[Barber] = relationship(back_populates="appointments", lazy="joined")
    service: Mapped[Service] = relationship(back_populates="appointments", lazy="joined")
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="appointment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def is_active(self) -> bool:
        return self.status == AppointmentStatus.CONFIRMED
