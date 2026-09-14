from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TenantScopedMixin, UUIDPrimaryKeyMixin


class AuditLogEntry(TenantScopedMixin, UUIDPrimaryKeyMixin, Base):
    """Неизменяемый журнал security-sensitive действий (роли, персонал).

    Без TimestampMixin намеренно: у записи журнала есть created_at, но нет
    updated_at — запись никогда не редактируется. Никогда не логировать сюда
    токены, пароли или платёжные секреты — только роли и telegram_id.
    """

    __tablename__ = "audit_log_entries"
    __table_args__ = (
        Index("ix_audit_log_entries_tenant_id_created_at", "tenant_id", "created_at"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[dict | None] = mapped_column(JSONB)
