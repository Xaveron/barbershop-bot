from __future__ import annotations

import uuid
from datetime import date, time

from sqlalchemy import func, or_, select

from app.database.models import Barber, BarberBranch, Branch, ScheduleException, WorkingSchedule
from app.database.repositories.base import TenantScopedRepository


class ScheduleRepository(TenantScopedRepository):
    async def _barber_belongs_to_tenant(self, barber_id: uuid.UUID) -> bool:
        """set_day/upsert_exception создают строку по чужому barber_id, если её ещё
        не было — get_day/_find_exception находят "нет строки" одинаково что для
        барбера чужого арендатора, что для несуществующего дня своего. Без этой
        проверки они молча создали бы запись, ссылающуюся на барбера другого
        арендатора (утечка не данных, но чужого FK — тоже нарушение изоляции)."""
        stmt = select(func.count()).select_from(Barber).where(
            Barber.id == barber_id, Barber.tenant_id == self.tenant_id
        )
        return bool(await self.session.scalar(stmt))

    async def _branch_belongs_to_tenant(self, branch_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(Branch).where(
            Branch.id == branch_id, Branch.tenant_id == self.tenant_id
        )
        return bool(await self.session.scalar(stmt))

    async def _barber_works_at_branch(self, barber_id: uuid.UUID, branch_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(BarberBranch).where(
            BarberBranch.tenant_id == self.tenant_id,
            BarberBranch.barber_id == barber_id,
            BarberBranch.branch_id == branch_id,
        )
        return bool(await self.session.scalar(stmt))

    async def _barber_and_branch_valid(self, barber_id: uuid.UUID, branch_id: uuid.UUID) -> bool:
        """Единая проверка перед созданием WorkingSchedule/ScheduleException:
        и барбер, и филиал — свои, и барбер реально работает в этом филиале."""
        if not await self._barber_belongs_to_tenant(barber_id):
            return False
        if not await self._branch_belongs_to_tenant(branch_id):
            return False
        return await self._barber_works_at_branch(barber_id, branch_id)

    # --- Недельный график ---------------------------------------------------
    async def list_week(self, barber_id: uuid.UUID, branch_id: uuid.UUID) -> list[WorkingSchedule]:
        stmt = (
            select(WorkingSchedule)
            .where(
                WorkingSchedule.barber_id == barber_id,
                WorkingSchedule.branch_id == branch_id,
                WorkingSchedule.tenant_id == self.tenant_id,
            )
            .order_by(WorkingSchedule.weekday)
        )
        return list(await self.session.scalars(stmt))

    async def get_day(
        self, barber_id: uuid.UUID, branch_id: uuid.UUID, weekday: int
    ) -> WorkingSchedule | None:
        stmt = select(WorkingSchedule).where(
            WorkingSchedule.barber_id == barber_id,
            WorkingSchedule.branch_id == branch_id,
            WorkingSchedule.weekday == weekday,
            WorkingSchedule.tenant_id == self.tenant_id,
        )
        return await self.session.scalar(stmt)

    async def set_day(
        self, barber_id: uuid.UUID, branch_id: uuid.UUID, weekday: int, start: time, end: time
    ) -> WorkingSchedule | None:
        if not await self._barber_and_branch_valid(barber_id, branch_id):
            return None
        record = await self.get_day(barber_id, branch_id, weekday)
        if record is None:
            record = WorkingSchedule(
                tenant_id=self.tenant_id,
                barber_id=barber_id,
                branch_id=branch_id,
                weekday=weekday,
                start_time=start,
                end_time=end,
            )
            self.session.add(record)
        else:
            record.start_time = start
            record.end_time = end
        await self.session.flush()
        return record

    async def clear_day(self, barber_id: uuid.UUID, branch_id: uuid.UUID, weekday: int) -> bool:
        record = await self.get_day(barber_id, branch_id, weekday)
        if record is None:
            return False
        await self.session.delete(record)
        await self.session.flush()
        return True

    # --- Исключения ---------------------------------------------------------
    async def get_exception(self, exception_id: uuid.UUID) -> ScheduleException | None:
        # session.get() не умеет добавлять tenant_id в WHERE — обязателен select().
        stmt = select(ScheduleException).where(
            ScheduleException.id == exception_id,
            ScheduleException.tenant_id == self.tenant_id,
        )
        return await self.session.scalar(stmt)

    async def list_exceptions(
        self,
        *,
        branch_id: uuid.UUID,
        barber_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        include_global: bool = True,
    ) -> list[ScheduleException]:
        stmt = select(ScheduleException).where(
            ScheduleException.tenant_id == self.tenant_id,
            ScheduleException.branch_id == branch_id,
        )
        if barber_id is not None:
            condition = ScheduleException.barber_id == barber_id
            if include_global:
                condition = or_(condition, ScheduleException.barber_id.is_(None))
            stmt = stmt.where(condition)
        if date_from is not None:
            stmt = stmt.where(ScheduleException.exception_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(ScheduleException.exception_date <= date_to)
        stmt = stmt.order_by(ScheduleException.exception_date)
        return list(await self.session.scalars(stmt))

    async def upsert_exception(
        self,
        *,
        branch_id: uuid.UUID,
        barber_id: uuid.UUID | None,
        exception_date: date,
        is_day_off: bool,
        start_time: time | None = None,
        end_time: time | None = None,
        reason: str | None = None,
    ) -> ScheduleException | None:
        if not await self._branch_belongs_to_tenant(branch_id):
            return None
        if barber_id is not None and not await self._barber_and_branch_valid(barber_id, branch_id):
            return None
        existing = await self._find_exception(barber_id, branch_id, exception_date)
        if existing is None:
            existing = ScheduleException(
                tenant_id=self.tenant_id,
                barber_id=barber_id,
                branch_id=branch_id,
                exception_date=exception_date,
            )
            self.session.add(existing)
        existing.is_day_off = is_day_off
        existing.start_time = None if is_day_off else start_time
        existing.end_time = None if is_day_off else end_time
        existing.reason = reason
        await self.session.flush()
        return existing

    async def delete_exception(self, exception: ScheduleException) -> None:
        await self.session.delete(exception)
        await self.session.flush()

    async def _find_exception(
        self, barber_id: uuid.UUID | None, branch_id: uuid.UUID, exception_date: date
    ) -> ScheduleException | None:
        stmt = select(ScheduleException).where(
            ScheduleException.exception_date == exception_date,
            ScheduleException.branch_id == branch_id,
            ScheduleException.tenant_id == self.tenant_id,
        )
        stmt = stmt.where(
            ScheduleException.barber_id.is_(None)
            if barber_id is None
            else ScheduleException.barber_id == barber_id
        )
        return await self.session.scalar(stmt)
