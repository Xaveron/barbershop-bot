from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Branch(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Филиал (физическая точка) арендатора. Один Tenant может иметь несколько
    Branch. name уникально в пределах арендатора. timezone читается
    ScheduleService/BookingService начиная с Phase 4 (см.
    docs/STAFF_SERVICE_BRANCH_DESIGN.md) — раньше вся бизнес-логика
    использовала settings.tz независимо от филиала."""

    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_branches_tenant_id_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(32))
    maps_url: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/Chisinau", server_default="Europe/Chisinau"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="MDL", server_default="MDL"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, index=True
    )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class BarberBranch(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Барбер работает в филиале (M2M) — один барбер может обслуживать
    несколько филиалов."""

    __tablename__ = "barber_branches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "barber_id", "branch_id",
            name="uq_barber_branches_tenant_id_barber_id_branch_id",
        ),
    )

    barber_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("barbers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )


class BranchService(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Услуга доступна в филиале. Отсутствие строки для (branch_id, service_id)
    означает «доступна везде» (так и заполняет бэкфилл миграции) — строка с
    is_active=false — это точечное исключение конкретного филиала."""

    __tablename__ = "branch_services"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "branch_id", "service_id",
            name="uq_branch_services_tenant_id_branch_id_service_id",
        ),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )


class StaffBranch(TenantScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ресурсное сужение доступа сотрудника к филиалу (см. docs/RBAC_DESIGN.md
    §6, AuthorizationService.can_access_branch). TENANT_OWNER/TENANT_ADMIN не
    нуждаются в строках — у них доступ ко всем филиалам арендатора."""

    __tablename__ = "staff_branches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "staff_member_id", "branch_id",
            name="uq_staff_branches_tenant_id_staff_member_id_branch_id",
        ),
    )

    staff_member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
