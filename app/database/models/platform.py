"""Платформенная идентичность — отдельно от tenant Role (Phase 8).

PlatformOperator НЕ является StaffMember и НЕ принадлежит ни одному
арендатору (нет tenant_id, нет TenantScopedMixin намеренно): платформенный
оператор может администрировать любое число арендаторов, а сама платформа —
не арендатор. См. docs/PLATFORM_CONTROL_PLANE.md."""

from __future__ import annotations

import enum

from sqlalchemy import BigInteger, Boolean, Enum, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PlatformRole(enum.StrEnum):
    """Один член сегодня намеренно: у платформы пока ровно один уровень
    доступа (полный). Отдельный enum, а не bool, — задел на будущее второе
    платформенное право без переименования колонки/модели."""

    PLATFORM_ADMIN = "platform_admin"


class PlatformOperator(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_operators"
    __table_args__ = (
        UniqueConstraint("telegram_user_id", name="uq_platform_operators_telegram_user_id"),
    )

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[PlatformRole] = mapped_column(
        Enum(
            PlatformRole,
            name="platform_role",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
