"""Статистика для админ-панели."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.repositories import AppointmentRepository, UserRepository
from app.utils.dt import combine_local, now_utc


@dataclass(slots=True)
class Stats:
    total_appointments: int = 0
    upcoming_appointments: int = 0
    today_appointments: int = 0
    month_appointments: int = 0
    cancelled_month: int = 0
    clients: int = 0
    revenue_month: float = 0.0
    revenue_today: float = 0.0
    top_services: list[tuple[str, int, float]] = field(default_factory=list)
    top_barbers: list[tuple[str, int, float]] = field(default_factory=list)


class StatsService:
    def __init__(self, session: AsyncSession, settings: Settings, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.settings = settings
        self.tz = settings.tz
        self.appointments = AppointmentRepository(session, tenant_id)
        self.users = UserRepository(session, tenant_id)

    async def collect(self) -> Stats:
        """Собирает статистику за 4 запроса: сводка, клиенты и два топа."""
        now = now_utc()
        today_local = now.astimezone(self.tz).date()
        day_start = combine_local(today_local, datetime.min.time(), self.tz)
        day_end = day_start + timedelta(days=1)
        month_start = combine_local(today_local.replace(day=1), datetime.min.time(), self.tz)
        far_future = now + timedelta(days=3650)

        summary = await self.appointments.summary(
            now=now, day_start=day_start, day_end=day_end, month_start=month_start
        )
        return Stats(
            total_appointments=summary["total"],
            upcoming_appointments=summary["upcoming"],
            today_appointments=summary["today"],
            month_appointments=summary["month"],
            cancelled_month=summary["cancelled_month"],
            clients=await self.users.count(),
            revenue_month=summary["revenue_month"],
            revenue_today=summary["revenue_today"],
            top_services=await self.appointments.top_services(start=month_start, end=far_future),
            top_barbers=await self.appointments.top_barbers(start=month_start, end=far_future),
        )
