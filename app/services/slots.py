"""Чистая (без БД) логика расчёта свободных слотов.

Модуль намеренно не зависит от SQLAlchemy и aiogram: его легко тестировать
и он остаётся единственным источником правды о том, какие слоты доступны.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class Interval:
    """Полуинтервал времени [start, end) с таймзоной."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Interval требует aware-datetime")
        if self.end <= self.start:
            raise ValueError("Конец интервала должен быть позже начала")

    def overlaps(self, other: Interval) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Interval) -> bool:
        return self.start <= other.start and other.end <= self.end

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class WorkWindow:
    """Рабочее окно в локальном времени барбершопа."""

    start: time
    end: time

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("Конец рабочего окна должен быть позже начала")


@dataclass(frozen=True, slots=True)
class DayOverride:
    """Исключение из графика на конкретный день."""

    is_day_off: bool
    window: WorkWindow | None = None

    def __post_init__(self) -> None:
        if not self.is_day_off and self.window is None:
            raise ValueError("Для рабочего исключения нужно указать окно")


def resolve_work_windows(
    *,
    weekly: WorkWindow | None,
    barber_override: DayOverride | None = None,
    global_override: DayOverride | None = None,
) -> list[WorkWindow]:
    """Определяет рабочие окна дня.

    Приоритет: выходной (любого уровня) → исключение барбера →
    исключение барбершопа → регулярный недельный график.
    """
    for override in (barber_override, global_override):
        if override is not None and override.is_day_off:
            return []
    for override in (barber_override, global_override):
        if override is not None and override.window is not None:
            return [override.window]
    return [weekly] if weekly is not None else []


def find_conflicts(candidate: Interval, busy: Iterable[Interval]) -> list[Interval]:
    """Все занятые интервалы, пересекающиеся с кандидатом."""
    return [interval for interval in busy if candidate.overlaps(interval)]


def is_slot_available(
    candidate: Interval,
    *,
    windows: Sequence[WorkWindow],
    busy: Sequence[Interval],
    tz: ZoneInfo,
    not_before: datetime,
) -> bool:
    """Проверяет один конкретный слот: рабочее время, занятость, прошедшее время."""
    if candidate.start < not_before:
        return False
    local_day = candidate.start.astimezone(tz).date()
    for window in windows:
        work = Interval(
            datetime.combine(local_day, window.start, tzinfo=tz),
            datetime.combine(local_day, window.end, tzinfo=tz),
        )
        if work.contains(candidate):
            return not find_conflicts(candidate, busy)
    return False


def generate_slots(
    *,
    day: date,
    tz: ZoneInfo,
    windows: Sequence[WorkWindow],
    busy: Sequence[Interval],
    duration_minutes: int,
    step_minutes: int,
    not_before: datetime,
    limit: int | None = None,
) -> list[datetime]:
    """Свободные начала слотов на день (локальные aware-datetime, по возрастанию).

    Учитывает: рабочие окна, длительность услуги, существующие записи,
    текущее время (`not_before`) и шаг сетки.
    """
    if duration_minutes <= 0 or step_minutes <= 0:
        raise ValueError("Длительность и шаг должны быть положительными")

    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes)
    found: list[datetime] = []

    for window in windows:
        window_start = datetime.combine(day, window.start, tzinfo=tz)
        window_end = datetime.combine(day, window.end, tzinfo=tz)
        cursor = window_start
        while cursor + duration <= window_end:
            if cursor >= not_before:
                candidate = Interval(cursor, cursor + duration)
                if not find_conflicts(candidate, busy):
                    found.append(cursor)
            cursor += step

    unique_sorted = sorted(set(found))
    return unique_sorted[:limit] if limit is not None else unique_sorted
