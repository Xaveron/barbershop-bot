from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.orm import joinedload

from app.database.models import Appointment, AppointmentStatus, Barber, Branch, Service, User
from app.database.repositories.base import TenantScopedRepository


def _with_relations(stmt: Select) -> Select:
    return stmt.options(
        joinedload(Appointment.user),
        joinedload(Appointment.branch),
        joinedload(Appointment.barber),
        joinedload(Appointment.service),
    )


def _local_today_window(now: datetime):
    """Branch-local "сегодня"/"этот месяц" — Branch.timezone авторитетен, а
    не settings.tz (см. Phase 9B §H-3). Появление колонки Branch.timezone в
    выражении требует JOIN на branches — вызывающий код обязан его сделать.

    timezone(zone, ts) переводит timestamptz в НАИВНЫЙ локальный timestamp
    по зоне ЭТОЙ строки (branch.timezone из JOIN), а не по одному общему
    процессному часовому поясу — поэтому границы дня/месяца вычисляются
    отдельно для каждой строки/филиала прямо в SQL, а не в Python по одному
    now = datetime.now(one_timezone)."""
    local_starts = func.timezone(Branch.timezone, Appointment.starts_at)
    local_now = func.timezone(Branch.timezone, now)
    today = func.date_trunc("day", local_starts) == func.date_trunc("day", local_now)
    since_month_start = local_starts >= func.date_trunc("month", local_now)
    return today, since_month_start


class AppointmentRepository(TenantScopedRepository):
    async def get(self, appointment_id: uuid.UUID) -> Appointment | None:
        stmt = _with_relations(
            select(Appointment).where(
                Appointment.id == appointment_id, Appointment.tenant_id == self.tenant_id
            )
        )
        return await self.session.scalar(stmt)

    async def list_for_barber_between(
        self,
        *,
        barber_id: uuid.UUID,
        start: datetime,
        end: datetime,
        statuses: Sequence[AppointmentStatus] = (AppointmentStatus.CONFIRMED,),
        exclude_id: uuid.UUID | None = None,
    ) -> list[Appointment]:
        """Записи барбера, пересекающиеся с интервалом [start, end)."""
        stmt = select(Appointment).where(
            Appointment.tenant_id == self.tenant_id,
            Appointment.barber_id == barber_id,
            Appointment.status.in_(statuses),
            Appointment.starts_at < end,
            Appointment.ends_at > start,
        )
        if exclude_id is not None:
            stmt = stmt.where(Appointment.id != exclude_id)
        stmt = stmt.order_by(Appointment.starts_at)
        return list(await self.session.scalars(stmt))

    async def list_upcoming_for_user(
        self, *, user_id: uuid.UUID, now: datetime, limit: int = 20
    ) -> list[Appointment]:
        stmt = _with_relations(
            select(Appointment).where(
                Appointment.tenant_id == self.tenant_id,
                Appointment.user_id == user_id,
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.ends_at > now,
            )
        ).order_by(Appointment.starts_at).limit(limit)
        return list((await self.session.scalars(stmt)).unique())

    async def count_active_for_user(self, *, user_id: uuid.UUID, now: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.tenant_id == self.tenant_id,
                Appointment.user_id == user_id,
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.ends_at > now,
            )
        )
        return await self.session.scalar(stmt) or 0

    async def list_between(
        self,
        *,
        start: datetime,
        end: datetime,
        statuses: Sequence[AppointmentStatus] | None = None,
        branch_ids: Collection[uuid.UUID] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Appointment]:
        stmt = select(Appointment).where(
            Appointment.tenant_id == self.tenant_id,
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
        )
        if statuses:
            stmt = stmt.where(Appointment.status.in_(statuses))
        if branch_ids is not None:
            stmt = stmt.where(Appointment.branch_id.in_(branch_ids))
        stmt = _with_relations(stmt).order_by(Appointment.starts_at).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).unique())

    async def summary(
        self,
        *,
        now: datetime,
        branch_ids: Collection[uuid.UUID] | None = None,
    ) -> dict[str, float]:
        """Все счётчики статистики одним запросом (агрегаты с FILTER).

        Раньше это было восемь отдельных SELECT-ов по одной и той же таблице.
        branch_ids=None — без ограничений (OWNER/ADMIN/платформенный
        SUPER_ADMIN); иначе — только доступные сотруднику филиалы (см. §C-1,
        Phase 9A, тот же контракт, что list_between/count_between).

        "today"/"month" — branch-local (см. _local_today_window, §H-3
        Phase 9B): для тенанта с филиалами в разных часовых поясах граница
        дня/месяца вычисляется отдельно для каждой строки через JOIN на
        branches, одним запросом — без риска задвоить/пропустить запись,
        как было бы при Python-цикле по отдельным часовым поясам."""
        done = (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED)
        today_local, since_month_start = _local_today_window(now)
        today_window = and_(today_local, Appointment.status.in_(done))
        month_window = and_(since_month_start, Appointment.status.in_(done))
        zero = func.cast(0, Appointment.price.type)

        stmt = (
            select(
                func.count().label("total"),
                func.count()
                .filter(
                    Appointment.status == AppointmentStatus.CONFIRMED,
                    Appointment.starts_at >= now,
                )
                .label("upcoming"),
                func.count().filter(today_window).label("today"),
                func.count().filter(month_window).label("month"),
                func.count()
                .filter(
                    since_month_start,
                    Appointment.status == AppointmentStatus.CANCELLED,
                )
                .label("cancelled_month"),
                func.coalesce(func.sum(Appointment.price).filter(month_window), zero).label(
                    "revenue_month"
                ),
                func.coalesce(func.sum(Appointment.price).filter(today_window), zero).label(
                    "revenue_today"
                ),
            )
            .select_from(Appointment)
            .join(Branch, Branch.id == Appointment.branch_id)
            .where(Appointment.tenant_id == self.tenant_id)
        )
        if branch_ids is not None:
            stmt = stmt.where(Appointment.branch_id.in_(branch_ids))

        row = (await self.session.execute(stmt)).one()
        return {
            "total": int(row.total),
            "upcoming": int(row.upcoming),
            "today": int(row.today),
            "month": int(row.month),
            "cancelled_month": int(row.cancelled_month),
            "revenue_month": float(row.revenue_month),
            "revenue_today": float(row.revenue_today),
        }

    async def count_between(
        self,
        *,
        start: datetime,
        end: datetime,
        statuses: Sequence[AppointmentStatus] | None = None,
        branch_ids: Collection[uuid.UUID] | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.tenant_id == self.tenant_id,
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
            )
        )
        if statuses:
            stmt = stmt.where(Appointment.status.in_(statuses))
        if branch_ids is not None:
            stmt = stmt.where(Appointment.branch_id.in_(branch_ids))
        return await self.session.scalar(stmt) or 0

    async def revenue_between(self, *, start: datetime, end: datetime) -> float:
        stmt = select(func.coalesce(func.sum(Appointment.price), 0)).where(
            Appointment.tenant_id == self.tenant_id,
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
            Appointment.status.in_(
                (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED)
            ),
        )
        return float(await self.session.scalar(stmt) or 0)

    async def top_services(
        self,
        *,
        now: datetime,
        limit: int = 5,
        branch_ids: Collection[uuid.UUID] | None = None,
    ) -> list[tuple[str, int, float]]:
        """«Этот месяц» — branch-local, тот же _local_today_window, что
        summary() (см. §H-3 Phase 9B): раньше принимал уже вычисленный в
        Python (settings.tz) [start, end), теперь вычисляет границу месяца
        для каждой строки сам через JOIN на branches."""
        _today_local, since_month_start = _local_today_window(now)
        total = func.count(Appointment.id).label("total")
        revenue = func.coalesce(func.sum(Appointment.price), 0).label("revenue")
        stmt = (
            select(Service.name, total, revenue)
            .join(Appointment, Appointment.service_id == Service.id)
            .join(Branch, Branch.id == Appointment.branch_id)
            .where(
                Appointment.tenant_id == self.tenant_id,
                since_month_start,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
            .group_by(Service.name)
            .order_by(total.desc())
            .limit(limit)
        )
        if branch_ids is not None:
            stmt = stmt.where(Appointment.branch_id.in_(branch_ids))
        rows = await self.session.execute(stmt)
        return [(row[0], int(row[1]), float(row[2])) for row in rows.all()]

    async def top_barbers(
        self,
        *,
        now: datetime,
        limit: int = 5,
        branch_ids: Collection[uuid.UUID] | None = None,
    ) -> list[tuple[str, int, float]]:
        """См. top_services — тот же branch-local "этот месяц"."""
        _today_local, since_month_start = _local_today_window(now)
        total = func.count(Appointment.id).label("total")
        revenue = func.coalesce(func.sum(Appointment.price), 0).label("revenue")
        stmt = (
            select(Barber.name, total, revenue)
            .join(Appointment, Appointment.barber_id == Barber.id)
            .join(Branch, Branch.id == Appointment.branch_id)
            .where(
                Appointment.tenant_id == self.tenant_id,
                since_month_start,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
            .group_by(Barber.name)
            .order_by(total.desc())
            .limit(limit)
        )
        if branch_ids is not None:
            stmt = stmt.where(Appointment.branch_id.in_(branch_ids))
        rows = await self.session.execute(stmt)
        return [(row[0], int(row[1]), float(row[2])) for row in rows.all()]

    async def list_for_export(
        self,
        *,
        start: datetime,
        end: datetime,
        branch_ids: Collection[uuid.UUID] | None = None,
    ) -> list[tuple[Appointment, User, Barber, Service]]:
        """start/end остаются обычным UTC-диапазоном (период экспорта из
        admin-UI, не "календарный день/месяц") — branch-local нужен только
        форматированию каждой строки в ExportService, для чего here нужен
        eager-loaded Appointment.branch (см. §H-3 Phase 9B)."""
        stmt = (
            select(Appointment, User, Barber, Service)
            .join(User, Appointment.user_id == User.id)
            .join(Barber, Appointment.barber_id == Barber.id)
            .join(Service, Appointment.service_id == Service.id)
            .options(joinedload(Appointment.branch))
            .where(
                Appointment.tenant_id == self.tenant_id,
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
            )
            .order_by(Appointment.starts_at)
        )
        if branch_ids is not None:
            stmt = stmt.where(Appointment.branch_id.in_(branch_ids))
        rows = await self.session.execute(stmt)
        return [(row[0], row[1], row[2], row[3]) for row in rows.all()]

    async def list_completed_in_ends_window(
        self, *, window_start: datetime, window_end: datetime
    ) -> list[Appointment]:
        """Завершённые записи, ends_at которых попадает в окно — для напоминания «вернись»."""
        stmt = _with_relations(
            select(Appointment).where(
                Appointment.tenant_id == self.tenant_id,
                Appointment.status == AppointmentStatus.COMPLETED,
                Appointment.ends_at >= window_start,
                Appointment.ends_at < window_end,
            )
        ).order_by(Appointment.ends_at.desc())
        return list((await self.session.scalars(stmt)).unique())

    async def mark_past_as_completed(self, *, now: datetime) -> int:
        stmt = (
            update(Appointment)
            .where(
                Appointment.tenant_id == self.tenant_id,
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.ends_at <= now,
            )
            .values(status=AppointmentStatus.COMPLETED)
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0
