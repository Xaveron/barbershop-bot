from __future__ import annotations

import enum
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, Enum, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TenantStatus(enum.StrEnum):
    """Жизненный цикл арендатора (Phase 5, см. docs/TENANT_ONBOARDING_DESIGN.md).

    SUSPENDED существует только как задел на будущее (биллинг и т.п.) — эта
    фаза не переводит в него ни одного арендатора и не строит вокруг него
    никакой бизнес-логики."""

    ONBOARDING = "onboarding"
    ACTIVE = "active"
    SUSPENDED = "suspended"


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
    # Дефолт языка для будущих сотрудников/клиентов этого арендатора, а не
    # authoritative значение поверх уже сохранённых StaffMember.language /
    # User.language_code (см. Phase 9E, app/services/locale.py). "ru" —
    # верифицированный текущий эффективный дефолт приложения (DEFAULT_LANGUAGE
    # в .env/Settings), которым бэкфилятся существующие арендаторы в 0013.
    default_language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="ru", server_default="ru"
    )
    shop_name: Mapped[str | None] = mapped_column(String(255))
    shop_address: Mapped[str | None] = mapped_column(Text)
    shop_phone: Mapped[str | None] = mapped_column(String(32))
    shop_maps_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    # Ни server_default, ни default сюда не ставим общим — миграция 0009 задаёт
    # server_default='active' только для бэкфилла существующих строк и сразу
    # снимает его; новые арендаторы получают default=ONBOARDING отсюда, из
    # Python-уровня модели, а не из колонки БД (см. docs/TENANT_ONBOARDING_DESIGN.md).
    status: Mapped[TenantStatus] = mapped_column(
        Enum(
            TenantStatus,
            name="tenant_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=TenantStatus.ONBOARDING,
        nullable=False,
    )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
