from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.orm import joinedload

from app.database.models import Appointment, AppointmentStatus, Barber, Service, User
from app.database.repositories.base import BaseRepository


def _with_relations(stmt: Select) -> Select:
    return stmt.options(
        joinedload(Appointment.user),
        joinedload(Appointment.barber),
        joinedload(Appointment.service),
    )


class AppointmentRepository(BaseRepository):
    async def get(self, appointment_id: uuid.UUID) -> Appointment | None:
        stmt = _with_relations(select(Appointment).where(Appointment.id == appointment_id))
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
        limit: int = 200,
        offset: int = 0,
    ) -> list[Appointment]:
        stmt = select(Appointment).where(
            Appointment.starts_at >= start, Appointment.starts_at < end
        )
        if statuses:
            stmt = stmt.where(Appointment.status.in_(statuses))
        stmt = _with_relations(stmt).order_by(Appointment.starts_at).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).unique())

    async def summary(
        self,
        *,
        now: datetime,
        day_start: datetime,
        day_end: datetime,
        month_start: datetime,
    ) -> dict[str, float]:
        """Все счётчики статистики одним запросом (агрегаты с FILTER).

        Раньше это было восемь отдельных SELECT-ов по одной и той же таблице.
        """
        done = (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED)
        today_window = and_(
            Appointment.starts_at >= day_start,
            Appointment.starts_at < day_end,
            Appointment.status.in_(done),
        )
        month_window = and_(
            Appointment.starts_at >= month_start, Appointment.status.in_(done)
        )
        zero = func.cast(0, Appointment.price.type)

        stmt = select(
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
                Appointment.starts_at >= month_start,
                Appointment.status == AppointmentStatus.CANCELLED,
            )
            .label("cancelled_month"),
            func.coalesce(func.sum(Appointment.price).filter(month_window), zero).label(
                "revenue_month"
            ),
            func.coalesce(func.sum(Appointment.price).filter(today_window), zero).label(
                "revenue_today"
            ),
        ).select_from(Appointment)

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
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.starts_at >= start, Appointment.starts_at < end)
        )
        if statuses:
            stmt = stmt.where(Appointment.status.in_(statuses))
        return await self.session.scalar(stmt) or 0

    async def revenue_between(
        self, *, start: datetime, end: datetime
    ) -> float:
        stmt = select(func.coalesce(func.sum(Appointment.price), 0)).where(
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
            Appointment.status.in_(
                (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED)
            ),
        )
        return float(await self.session.scalar(stmt) or 0)

    async def top_services(
        self, *, start: datetime, end: datetime, limit: int = 5
    ) -> list[tuple[str, int, float]]:
        total = func.count(Appointment.id).label("total")
        revenue = func.coalesce(func.sum(Appointment.price), 0).label("revenue")
        stmt = (
            select(Service.name, total, revenue)
            .join(Appointment, Appointment.service_id == Service.id)
            .where(
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
            .group_by(Service.name)
            .order_by(total.desc())
            .limit(limit)
        )
        rows = await self.session.execute(stmt)
        return [(row[0], int(row[1]), float(row[2])) for row in rows.all()]

    async def top_barbers(
        self, *, start: datetime, end: datetime, limit: int = 5
    ) -> list[tuple[str, int, float]]:
        total = func.count(Appointment.id).label("total")
        revenue = func.coalesce(func.sum(Appointment.price), 0).label("revenue")
        stmt = (
            select(Barber.name, total, revenue)
            .join(Appointment, Appointment.barber_id == Barber.id)
            .where(
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
            .group_by(Barber.name)
            .order_by(total.desc())
            .limit(limit)
        )
        rows = await self.session.execute(stmt)
        return [(row[0], int(row[1]), float(row[2])) for row in rows.all()]

    async def list_for_export(
        self, *, start: datetime, end: datetime
    ) -> list[tuple[Appointment, User, Barber, Service]]:
        stmt = (
            select(Appointment, User, Barber, Service)
            .join(User, Appointment.user_id == User.id)
            .join(Barber, Appointment.barber_id == Barber.id)
            .join(Service, Appointment.service_id == Service.id)
            .where(Appointment.starts_at >= start, Appointment.starts_at < end)
            .order_by(Appointment.starts_at)
        )
        rows = await self.session.execute(stmt)
        return [(row[0], row[1], row[2], row[3]) for row in rows.all()]

    async def list_completed_in_ends_window(
        self, *, window_start: datetime, window_end: datetime
    ) -> list[Appointment]:
        """Завершённые записи, ends_at которых попадает в окно — для напоминания «вернись»."""
        stmt = _with_relations(
            select(Appointment).where(
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
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.ends_at <= now,
            )
            .values(status=AppointmentStatus.COMPLETED)
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0
