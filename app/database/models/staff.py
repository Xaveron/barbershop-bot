from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, UniqueConstraint, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.barber import Barber


class Role(enum.StrEnum):
    """Роли уровня арендатора. SUPER_ADMIN сюда намеренно не входит — это
    платформенная роль, живущая только в Settings.admin_ids (ADMIN_ID), и ни
    один код приложения не пишет её в StaffMember.role. Это структурная
    гарантия «tenant admin не может выдать SUPER_ADMIN», а не рантайм-проверка,
    которую можно забыть добавить: Role("super_admin") невозможен в принципе.
    """

    TENANT_OWNER = "tenant_owner"
    TENANT_ADMIN = "tenant_admin"
    MANAGER = "manager"
    RECEPTIONIST = "receptionist"
    BARBER = "barber"


class Permission(enum.StrEnum):
    MANAGE_TENANT = "manage_tenant"
    MANAGE_STAFF = "manage_staff"
    VIEW_STAFF = "view_staff"
    MANAGE_SERVICES = "manage_services"
    MANAGE_SCHEDULE = "manage_schedule"
    MANAGE_BOOKINGS = "manage_bookings"
    MANAGE_CUSTOMERS = "manage_customers"
    VIEW_CUSTOMERS = "view_customers"
    VIEW_ANALYTICS = "view_analytics"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_SUBSCRIPTION = "manage_subscription"


# Статическая политика: как NAMING_CONVENTION в app/database/base.py, это
# константа кода, а не настраиваемая через БД сущность — в приложении нет
# прецедента для DB-driven policy. См. docs/RBAC_DESIGN.md §5 за обоснованием
# построчно.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.TENANT_OWNER: frozenset(Permission),
    Role.TENANT_ADMIN: frozenset(Permission) - {Permission.MANAGE_SUBSCRIPTION},
    Role.MANAGER: frozenset(
        {
            Permission.VIEW_STAFF,
            Permission.MANAGE_SERVICES,
            Permission.MANAGE_SCHEDULE,
            Permission.MANAGE_BOOKINGS,
            Permission.MANAGE_CUSTOMERS,
            Permission.VIEW_ANALYTICS,
        }
    ),
    Role.RECEPTIONIST: frozenset({Permission.MANAGE_BOOKINGS, Permission.VIEW_CUSTOMERS}),
    Role.BARBER: frozenset({Permission.VIEW_CUSTOMERS}),
}


class StaffMember(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Сотрудник арендатора с ролью в системе.

    Не путать с Barber — мастером-услугодателем в бизнес-модели бронирования.
    Один человек может быть и тем и другим, отсюда необязательная barber_id:
    задел на ресурсное сужение прав (BARBER видит только свою запись), см.
    docs/RBAC_DESIGN.md §6. Ни один хендлер сегодня не использует эту связь —
    в приложении нет флоу, где барбер сам заходит в бота как сотрудник.
    """

    __tablename__ = "staff_members"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "telegram_id", name="uq_staff_members_tenant_id_telegram_id"
        ),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="staff_role", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        nullable=False,
    )
    barber_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("barbers.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )

    barber: Mapped[Barber | None] = relationship()
