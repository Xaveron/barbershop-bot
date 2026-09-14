from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.appointment import Appointment


class Service(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Услуга барбершопа: цена и длительность."""

    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_services_tenant_id_name"),
        CheckConstraint("duration_minutes > 0 AND duration_minutes <= 480", name="duration_range"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), default="MDL", server_default="MDL", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=100, server_default=text("100"), nullable=False
    )

    appointments: Mapped[list[Appointment]] = relationship(back_populates="service")
