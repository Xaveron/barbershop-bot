"""Тесты рабочего графика, выходных и исключений."""

from __future__ import annotations

from datetime import date, time

from app.services.schedule import ScheduleContext, ScheduleService
from app.services.slots import DayOverride, WorkWindow, generate_slots, resolve_work_windows
from tests.conftest import local

MORNING = WorkWindow(time(10, 0), time(19, 0))
SHORT = WorkWindow(time(12, 0), time(16, 0))
DAY = date(2026, 9, 15)


def test_weekly_schedule_used_when_no_exceptions():
    assert resolve_work_windows(weekly=MORNING) == [MORNING]


def test_no_weekly_schedule_means_day_off():
    assert resolve_work_windows(weekly=None) == []


def test_barber_day_off_overrides_weekly():
    windows = resolve_work_windows(
        weekly=MORNING, barber_override=DayOverride(is_day_off=True)
    )
    assert windows == []


def test_global_holiday_overrides_weekly():
    windows = resolve_work_windows(
        weekly=MORNING, global_override=DayOverride(is_day_off=True)
    )
    assert windows == []


def test_barber_special_hours_override_weekly():
    windows = resolve_work_windows(
        weekly=MORNING, barber_override=DayOverride(is_day_off=False, window=SHORT)
    )
    assert windows == [SHORT]


def test_barber_override_wins_over_global_override():
    windows = resolve_work_windows(
        weekly=MORNING,
        barber_override=DayOverride(is_day_off=False, window=SHORT),
        global_override=DayOverride(is_day_off=False, window=WorkWindow(time(9, 0), time(11, 0))),
    )
    assert windows == [SHORT]


def test_day_off_wins_even_if_other_level_sets_hours():
    windows = resolve_work_windows(
        weekly=MORNING,
        barber_override=DayOverride(is_day_off=False, window=SHORT),
        global_override=DayOverride(is_day_off=True),
    )
    assert windows == []


def test_exception_shrinks_available_slots(tz):
    slots = generate_slots(
        day=DAY,
        tz=tz,
        windows=resolve_work_windows(
            weekly=MORNING, barber_override=DayOverride(is_day_off=False, window=SHORT)
        ),
        busy=[],
        duration_minutes=60,
        step_minutes=60,
        not_before=local(2026, 9, 1, 0, 0),
    )
    assert slots == [
        local(2026, 9, 15, 12),
        local(2026, 9, 15, 13),
        local(2026, 9, 15, 14),
        local(2026, 9, 15, 15),
    ]


def test_schedule_context_resolution_uses_weekday(tz):
    context = ScheduleContext(
        weekly={DAY.weekday(): MORNING},
        barber_overrides={},
        global_overrides={date(2026, 9, 16): DayOverride(is_day_off=True)},
        busy=[],
    )
    assert ScheduleService._windows_for(context, DAY) == [MORNING]
    assert ScheduleService._windows_for(context, date(2026, 9, 16)) == []
