"""Привязка Telegram-бота к арендатору (Phase 7).

Ровно один арендатор на bot (UniqueConstraint(telegram_bot_id), глобальный —
не (tenant_id, telegram_bot_id)), но у арендатора может быть несколько ботов.
Именно эта таблица — единственный источник истины "какому арендатору
принадлежит этот bot", вместо process-global default tenant (см.
docs/BOT_IDENTITY_ARCHITECTURE.md)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class TelegramBotIdentity(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Никогда не хранит raw bot token — только telegram_bot_id, полученный
    из Bot.id/getMe() (см. app/register_bot.py), и username для отображения/
    логов (username может меняться, identity — нет)."""

    __tablename__ = "telegram_bot_identities"
    __table_args__ = (
        UniqueConstraint("telegram_bot_id", name="uq_telegram_bot_identities_telegram_bot_id"),
    )

    telegram_bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
