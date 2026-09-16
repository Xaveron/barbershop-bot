"""Статистика для админ-панели."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.repositories import AppointmentRepository, UserRepository
from app.utils.dt import now_utc


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
    """"Сегодня"/"этот месяц" вычисляются branch-local (Branch.timezone —
    authoritative, см. §H-3 Phase 9B), а не по одному общему settings.tz:
    для тенанта с филиалами в разных часовых поясах "сегодня" у каждой
    записи — это сегодня по часовому поясу ЕЁ ФИЛИАЛА. Вся арифметика дат
    живёт в AppointmentRepository (JOIN на branches + timezone()/date_trunc()
    в SQL), а не здесь — этот сервис лишь передаёт "сейчас" (единственный
    момент, общий для всех записей и филиалов, конвертируемый в локальное
    время каждой строки уже в БД)."""

    def __init__(self, session: AsyncSession, settings: Settings, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.settings = settings
        self.appointments = AppointmentRepository(session, tenant_id)
        self.users = UserRepository(session, tenant_id)

    async def collect(
        self, *, branch_ids: Collection[uuid.UUID] | None = None
    ) -> Stats:
        """Собирает статистику за 4 запроса: сводка, клиенты и два топа.

        branch_ids=None — без ограничений (OWNER/ADMIN/платформенный
        SUPER_ADMIN); иначе — статистика только по доступным сотруднику
        филиалам (см. §C-1, Phase 9A)."""
        now = now_utc()
        summary = await self.appointments.summary(now=now, branch_ids=branch_ids)
        return Stats(
            total_appointments=summary["total"],
            upcoming_appointments=summary["upcoming"],
            today_appointments=summary["today"],
            month_appointments=summary["month"],
            cancelled_month=summary["cancelled_month"],
            clients=await self.users.count(branch_ids=branch_ids),
            revenue_month=summary["revenue_month"],
            revenue_today=summary["revenue_today"],
            top_services=await self.appointments.top_services(now=now, branch_ids=branch_ids),
            top_barbers=await self.appointments.top_barbers(now=now, branch_ids=branch_ids),
        )
