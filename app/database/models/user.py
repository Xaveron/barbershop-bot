from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.appointment import Appointment


class User(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Клиент барбершопа (пользователь Telegram)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "telegram_id", name="uq_users_tenant_id_telegram_id"),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    language_code: Mapped[str | None] = mapped_column(String(8))
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    appointments: Mapped[list[Appointment]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"{self.full_name} (@{self.username})"
        return self.full_name
