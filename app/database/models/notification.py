from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.appointment import Appointment


class NotificationKind(enum.StrEnum):
    REMINDER_24H = "reminder_24h"
    REMINDER_2H = "reminder_2h"
    RETURN_REMINDER = "return_reminder"


class NotificationStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Запланированное напоминание.

    UNIQUE(appointment_id, kind) гарантирует идемпотентность:
    одно и то же напоминание физически невозможно отправить дважды.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("appointment_id", "kind", name="uq_notifications_appointment_id_kind"),
        Index("ix_notifications_status_scheduled_for", "status", "scheduled_for"),
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[NotificationKind] = mapped_column(
        Enum(
            NotificationKind,
            name="notification_kind",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(
            NotificationStatus,
            name="notification_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
        nullable=False,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text)

    appointment: Mapped[Appointment] = relationship(back_populates="notifications")
