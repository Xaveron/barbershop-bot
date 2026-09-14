"""Сервис расписания: превращает данные БД в свободные слоты."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import ScheduleException, WorkingSchedule
from app.database.repositories import AppointmentRepository, ScheduleRepository
from app.services.slots import (
    DayOverride,
    Interval,
    WorkWindow,
    generate_slots,
    is_slot_available,
    resolve_work_windows,
)
from app.utils.dt import combine_local, now_utc


@dataclass(slots=True)
class ScheduleContext:
    """Данные расписания барбера за период — загружаются одним пакетом запросов."""

    weekly: dict[int, WorkWindow]
    barber_overrides: dict[date, DayOverride]
    global_overrides: dict[date, DayOverride]
    busy: list[Interval]


def _to_override(exception: ScheduleException) -> DayOverride:
    if exception.is_day_off or exception.start_time is None or exception.end_time is None:
        return DayOverride(is_day_off=True)
    return DayOverride(
        is_day_off=False,
        window=WorkWindow(start=exception.start_time, end=exception.end_time),
    )


def _to_window(schedule: WorkingSchedule) -> WorkWindow:
    return WorkWindow(start=schedule.start_time, end=schedule.end_time)


class ScheduleService:
    def __init__(self, session: AsyncSession, settings: Settings, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.settings = settings
        self.tenant_id = tenant_id
        self.tz = settings.tz
        self.schedules = ScheduleRepository(session, tenant_id)
        self.appointments = AppointmentRepository(session, tenant_id)

    # --- Публичное API ------------------------------------------------------
    async def available_days(
        self,
        *,
        barber_id: uuid.UUID,
        duration_minutes: int,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> list[date]:
        """Даты в горизонте бронирования, где есть хотя бы один свободный слот."""
        first_day = now_utc().astimezone(self.tz).date()
        last_day = first_day + timedelta(days=self.settings.booking_horizon_days - 1)
        context = await self._load_context(
            barber_id=barber_id,
            first_day=first_day,
            last_day=last_day,
            exclude_appointment_id=exclude_appointment_id,
        )
        not_before = self._not_before()

        days: list[date] = []
        current = first_day
        while current <= last_day:
            slots = generate_slots(
                day=current,
                tz=self.tz,
                windows=self._windows_for(context, current),
                busy=context.busy,
                duration_minutes=duration_minutes,
                step_minutes=self.settings.slot_step_minutes,
                not_before=not_before,
                limit=1,
            )
            if slots:
                days.append(current)
            current += timedelta(days=1)
        return days

    async def available_slots(
        self,
        *,
        barber_id: uuid.UUID,
        day: date,
        duration_minutes: int,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> list[datetime]:
        """Свободные слоты конкретного дня (локальное время)."""
        context = await self._load_context(
            barber_id=barber_id,
            first_day=day,
            last_day=day,
            exclude_appointment_id=exclude_appointment_id,
        )
        return generate_slots(
            day=day,
            tz=self.tz,
            windows=self._windows_for(context, day),
            busy=context.busy,
            duration_minutes=duration_minutes,
            step_minutes=self.settings.slot_step_minutes,
            not_before=self._not_before(),
            limit=self.settings.max_slots_per_day,
        )

    async def is_slot_available(
        self,
        *,
        barber_id: uuid.UUID,
        start: datetime,
        duration_minutes: int,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> bool:
        """Финальная проверка перед записью (выполняется внутри транзакции с блокировкой)."""
        local_start = start.astimezone(self.tz)
        day = local_start.date()
        context = await self._load_context(
            barber_id=barber_id,
            first_day=day,
            last_day=day,
            exclude_appointment_id=exclude_appointment_id,
        )
        candidate = Interval(local_start, local_start + timedelta(minutes=duration_minutes))
        # Горизонт бронирования: callback_data можно подделать, а показанные
        # даты ограничены booking_horizon_days.
        if candidate.end > self._not_after():
            return False
        return is_slot_available(
            candidate,
            windows=self._windows_for(context, day),
            busy=context.busy,
            tz=self.tz,
            not_before=self._not_before(),
        )

    async def week_summary(self, barber_id: uuid.UUID) -> dict[int, WorkWindow | None]:
        """Недельный график барбера для админ-панели."""
        records = await self.schedules.list_week(barber_id)
        summary: dict[int, WorkWindow | None] = dict.fromkeys(range(7))
        for record in records:
            summary[record.weekday] = _to_window(record)
        return summary

    # --- Внутреннее ---------------------------------------------------------
    def _not_before(self) -> datetime:
        return now_utc() + timedelta(minutes=self.settings.min_lead_minutes)

    def _not_after(self) -> datetime:
        """Полночь после последнего дня, открытого для записи."""
        horizon_day = now_utc().astimezone(self.tz).date() + timedelta(
            days=self.settings.booking_horizon_days
        )
        return combine_local(horizon_day, datetime.min.time(), self.tz)

    @staticmethod
    def _windows_for(context: ScheduleContext, day: date) -> list[WorkWindow]:
        return resolve_work_windows(
            weekly=context.weekly.get(day.weekday()),
            barber_override=context.barber_overrides.get(day),
            global_override=context.global_overrides.get(day),
        )

    async def _load_context(
        self,
        *,
        barber_id: uuid.UUID,
        first_day: date,
        last_day: date,
        exclude_appointment_id: uuid.UUID | None,
    ) -> ScheduleContext:
        weekly = {
            schedule.weekday: _to_window(schedule)
            for schedule in await self.schedules.list_week(barber_id)
        }

        barber_overrides: dict[date, DayOverride] = {}
        global_overrides: dict[date, DayOverride] = {}
        exceptions = await self.schedules.list_exceptions(
            barber_id=barber_id,
            date_from=first_day,
            date_to=last_day,
            include_global=True,
        )
        for exception in exceptions:
            target = global_overrides if exception.is_global else barber_overrides
            target[exception.exception_date] = _to_override(exception)

        period_start = combine_local(first_day, datetime.min.time(), self.tz)
        period_end = combine_local(last_day + timedelta(days=1), datetime.min.time(), self.tz)
        appointments = await self.appointments.list_for_barber_between(
            barber_id=barber_id,
            start=period_start,
            end=period_end,
            exclude_id=exclude_appointment_id,
        )
        busy = [
            Interval(item.starts_at.astimezone(self.tz), item.ends_at.astimezone(self.tz))
            for item in appointments
        ]
        return ScheduleContext(
            weekly=weekly,
            barber_overrides=barber_overrides,
            global_overrides=global_overrides,
            busy=busy,
        )
