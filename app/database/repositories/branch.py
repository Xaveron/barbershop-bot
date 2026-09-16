from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database.models import (
    Barber,
    BarberBranch,
    Branch,
    BranchService,
    Service,
    StaffBranch,
    StaffMember,
)
from app.database.repositories.base import TenantScopedRepository
from app.database.repositories.tenant import TenantRepository


class BranchRepository(TenantScopedRepository):
    async def get(self, branch_id: uuid.UUID) -> Branch | None:
        # session.get() не умеет добавлять tenant_id в WHERE — обязателен select().
        stmt = select(Branch).where(Branch.id == branch_id, Branch.tenant_id == self.tenant_id)
        return await self.session.scalar(stmt)

    async def get_active(self, branch_id: uuid.UUID) -> Branch | None:
        branch = await self.get(branch_id)
        return branch if branch is not None and branch.is_active else None

    async def list_active(self) -> list[Branch]:
        stmt = (
            select(Branch)
            .where(Branch.tenant_id == self.tenant_id, Branch.is_active.is_(True))
            .order_by(Branch.name)
        )
        return list(await self.session.scalars(stmt))

    async def list_all(self, *, limit: int | None = None, offset: int = 0) -> list[Branch]:
        """limit=None — полный список (для operational-пикеров, которым
        нужны ВСЕ филиалы, не одна страница); limit задан — одна страница
        admin-списка (см. Phase 9C §M-6). id как tie-breaker гарантирует
        стабильный порядок между страницами."""
        stmt = (
            select(Branch)
            .where(Branch.tenant_id == self.tenant_id)
            .order_by(Branch.is_active.desc(), Branch.name, Branch.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(Branch).where(Branch.tenant_id == self.tenant_id)
        return await self.session.scalar(stmt) or 0

    async def create(
        self,
        *,
        name: str,
        address: str | None = None,
        phone: str | None = None,
        timezone: str | None = None,
        currency: str | None = None,
    ) -> Branch:
        """timezone/currency по умолчанию наследуются от арендатора, а не от
        жёстко зашитых дефолтов колонок — иначе филиал в арендаторе с
        нестандартными зоной/валютой молча получил бы неверные значения (см.
        docs/STAFF_SERVICE_BRANCH_DESIGN.md, docs/TENANT_ONBOARDING_DESIGN.md)."""
        if timezone is None or currency is None:
            tenant = await TenantRepository(self.session).get(self.tenant_id)
            if timezone is None:
                timezone = tenant.timezone if tenant is not None else "Europe/Chisinau"
            if currency is None:
                currency = tenant.currency if tenant is not None else "MDL"
        branch = Branch(
            tenant_id=self.tenant_id,
            name=name,
            address=address,
            phone=phone,
            timezone=timezone,
            currency=currency,
        )
        self.session.add(branch)
        await self.session.flush()
        return branch

    async def _belongs_to_tenant(self, model, entity_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(model).where(
            model.id == entity_id, model.tenant_id == self.tenant_id
        )
        return bool(await self.session.scalar(stmt))

    async def assign_barber(
        self, *, barber_id: uuid.UUID, branch_id: uuid.UUID
    ) -> BarberBranch | None:
        """Возвращает None, если barber_id или branch_id принадлежат другому
        арендатору — тот же паттерн, что ScheduleRepository._barber_belongs_to_tenant."""
        if not await self._belongs_to_tenant(Barber, barber_id):
            return None
        if not await self._belongs_to_tenant(Branch, branch_id):
            return None
        existing = await self.session.scalar(
            select(BarberBranch).where(
                BarberBranch.tenant_id == self.tenant_id,
                BarberBranch.barber_id == barber_id,
                BarberBranch.branch_id == branch_id,
            )
        )
        if existing is not None:
            return existing
        link = BarberBranch(tenant_id=self.tenant_id, barber_id=barber_id, branch_id=branch_id)
        self.session.add(link)
        await self.session.flush()
        return link

    async def assign_service(
        self, *, service_id: uuid.UUID, branch_id: uuid.UUID, is_active: bool = True
    ) -> BranchService | None:
        """Тот же guard-паттерн, что assign_barber, но для доступности услуги в филиале."""
        if not await self._belongs_to_tenant(Service, service_id):
            return None
        if not await self._belongs_to_tenant(Branch, branch_id):
            return None
        existing = await self.session.scalar(
            select(BranchService).where(
                BranchService.tenant_id == self.tenant_id,
                BranchService.branch_id == branch_id,
                BranchService.service_id == service_id,
            )
        )
        if existing is not None:
            existing.is_active = is_active
            await self.session.flush()
            return existing
        link = BranchService(
            tenant_id=self.tenant_id, branch_id=branch_id, service_id=service_id,
            is_active=is_active,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def barber_works_at_branch(self, *, barber_id: uuid.UUID, branch_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(BarberBranch).where(
            BarberBranch.tenant_id == self.tenant_id,
            BarberBranch.barber_id == barber_id,
            BarberBranch.branch_id == branch_id,
        )
        return bool(await self.session.scalar(stmt))

    async def service_available_at_branch(
        self, *, service_id: uuid.UUID, branch_id: uuid.UUID
    ) -> bool:
        """Отсутствие строки означает «доступна» (opt-out, см. docстроку
        BranchService) — раньше здесь по ошибке возвращался False при
        отсутствии строки; метод нигде не вызывался, поэтому баг ни разу не
        сработал (см. docs/STAFF_SERVICE_BRANCH_DESIGN.md)."""
        stmt = select(BranchService.is_active).where(
            BranchService.tenant_id == self.tenant_id,
            BranchService.branch_id == branch_id,
            BranchService.service_id == service_id,
        )
        row = await self.session.scalar(stmt)
        return True if row is None else row

    async def unassign_barber(self, *, barber_id: uuid.UUID, branch_id: uuid.UUID) -> bool:
        link = await self.session.scalar(
            select(BarberBranch).where(
                BarberBranch.tenant_id == self.tenant_id,
                BarberBranch.barber_id == barber_id,
                BarberBranch.branch_id == branch_id,
            )
        )
        if link is None:
            return False
        await self.session.delete(link)
        await self.session.flush()
        return True

    async def assign_staff(
        self, *, staff_member_id: uuid.UUID, branch_id: uuid.UUID
    ) -> StaffBranch | None:
        """Тот же guard-паттерн, что assign_barber, но для доступа сотрудника к филиалу."""
        if not await self._belongs_to_tenant(StaffMember, staff_member_id):
            return None
        if not await self._belongs_to_tenant(Branch, branch_id):
            return None
        existing = await self.session.scalar(
            select(StaffBranch).where(
                StaffBranch.tenant_id == self.tenant_id,
                StaffBranch.staff_member_id == staff_member_id,
                StaffBranch.branch_id == branch_id,
            )
        )
        if existing is not None:
            return existing
        link = StaffBranch(
            tenant_id=self.tenant_id, staff_member_id=staff_member_id, branch_id=branch_id
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def unassign_staff(self, *, staff_member_id: uuid.UUID, branch_id: uuid.UUID) -> bool:
        link = await self.session.scalar(
            select(StaffBranch).where(
                StaffBranch.tenant_id == self.tenant_id,
                StaffBranch.staff_member_id == staff_member_id,
                StaffBranch.branch_id == branch_id,
            )
        )
        if link is None:
            return False
        await self.session.delete(link)
        await self.session.flush()
        return True

    async def list_branches_for_staff(self, staff_member_id: uuid.UUID) -> list[Branch]:
        stmt = (
            select(Branch)
            .join(StaffBranch, StaffBranch.branch_id == Branch.id)
            .where(
                Branch.tenant_id == self.tenant_id,
                StaffBranch.tenant_id == self.tenant_id,
                StaffBranch.staff_member_id == staff_member_id,
            )
            .order_by(Branch.name)
        )
        return list(await self.session.scalars(stmt))

    async def list_for_barber(self, barber_id: uuid.UUID) -> list[Branch]:
        stmt = (
            select(Branch)
            .join(BarberBranch, BarberBranch.branch_id == Branch.id)
            .where(
                Branch.tenant_id == self.tenant_id,
                BarberBranch.tenant_id == self.tenant_id,
                BarberBranch.barber_id == barber_id,
            )
            .order_by(Branch.name)
        )
        return list(await self.session.scalars(stmt))

    async def accessible_branch_ids_for_staff(
        self, staff_member_id: uuid.UUID
    ) -> frozenset[uuid.UUID]:
        stmt = select(StaffBranch.branch_id).where(
            StaffBranch.tenant_id == self.tenant_id,
            StaffBranch.staff_member_id == staff_member_id,
        )
        return frozenset(await self.session.scalars(stmt))
