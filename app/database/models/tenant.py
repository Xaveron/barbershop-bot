from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Арендатор SaaS: один барбершоп.

    Phase 1: в базе ровно одна строка (единственный Telegram-бот, см.
    app/main.py). Поля shop_* остаются заделом (Settings — источник истины
    для контактов барбершопа), но timezone используется как запасной вариант
    при создании нового филиала без явно указанной зоны (см. BranchRepository.create)."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/Chisinau", server_default="Europe/Chisinau"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="MDL", server_default="MDL"
    )
    shop_name: Mapped[str | None] = mapped_column(String(255))
    shop_address: Mapped[str | None] = mapped_column(Text)
    shop_phone: Mapped[str | None] = mapped_column(String(32))
    shop_maps_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
