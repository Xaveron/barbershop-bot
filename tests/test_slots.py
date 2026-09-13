"""Тесты расчёта свободных слотов."""

from __future__ import annotations

from datetime import date, time, timedelta
from itertools import pairwise

import pytest

from app.services.slots import (
    Interval,
    WorkWindow,
    find_conflicts,
    generate_slots,
    is_slot_available,
)
from tests.conftest import local

DAY = date(2026, 9, 15)  # вторник
PAST = local(2026, 9, 15, 0, 0)


def test_interval_requires_positive_duration(tz):
    with pytest.raises(ValueError):
        Interval(local(2026, 9, 15, 12), local(2026, 9, 15, 12))


def test_interval_overlaps_is_half_open():
    first = Interval(local(2026, 9, 15, 12), local(2026, 9, 15, 13))
    touching = Interval(local(2026, 9, 15, 13), local(2026, 9, 15, 14))
    crossing = Interval(local(2026, 9, 15, 12, 30), local(2026, 9, 15, 13, 30))

    assert not first.overlaps(touching), "стык интервалов не считается пересечением"
    assert first.overlaps(crossing)
    assert crossing.overlaps(first)


def test_generate_slots_basic_grid(tz, work_window):
    slots = generate_slots(
        day=DAY,
        tz=tz,
        windows=[work_window],
        busy=[],
        duration_minutes=60,
        step_minutes=30,
        not_before=PAST,
    )
    assert slots[0] == local(2026, 9, 15, 10, 0)
    assert slots[-1] == local(2026, 9, 15, 18, 0)
    assert len(slots) == 17


def test_generate_slots_respects_duration_at_window_end(tz):
    slots = generate_slots(
        day=DAY,
        tz=tz,
        windows=[WorkWindow(time(10, 0), time(11, 0))],
        busy=[],
        duration_minutes=45,
        step_minutes=15,
        not_before=PAST,
    )
    assert slots == [local(2026, 9, 15, 10, 0), local(2026, 9, 15, 10, 15)]


def test_generate_slots_excludes_busy_intervals(tz, work_window):
    busy = [Interval(local(2026, 9, 15, 12, 0), local(2026, 9, 15, 13, 0))]
    slots = generate_slots(
        day=DAY,
        tz=tz,
        windows=[work_window],
        busy=busy,
        duration_minutes=60,
        step_minutes=30,
        not_before=PAST,
    )
    assert local(2026, 9, 15, 11, 30) not in slots
    assert local(2026, 9, 15, 12, 0) not in slots
    assert local(2026, 9, 15, 12, 30) not in slots
    assert local(2026, 9, 15, 13, 0) in slots
    assert local(2026, 9, 15, 11, 0) in slots


def test_generate_slots_hides_past_slots(tz, work_window):
    slots = generate_slots(
        day=DAY,
        tz=tz,
        windows=[work_window],
        busy=[],
        duration_minutes=60,
        step_minutes=30,
        not_before=local(2026, 9, 15, 14, 10),
    )
    assert slots[0] == local(2026, 9, 15, 14, 30)
    assert all(slot >= local(2026, 9, 15, 14, 10) for slot in slots)


def test_generate_slots_empty_when_no_windows(tz):
    assert generate_slots(
        day=DAY,
        tz=tz,
        windows=[],
        busy=[],
        duration_minutes=30,
        step_minutes=15,
        not_before=PAST,
    ) == []


def test_generate_slots_limit(tz, work_window):
    slots = generate_slots(
        day=DAY,
        tz=tz,
        windows=[work_window],
        busy=[],
        duration_minutes=30,
        step_minutes=15,
        not_before=PAST,
        limit=5,
    )
    assert len(slots) == 5


def test_generate_slots_rejects_invalid_arguments(tz, work_window):
    with pytest.raises(ValueError):
        generate_slots(
            day=DAY,
            tz=tz,
            windows=[work_window],
            busy=[],
            duration_minutes=0,
            step_minutes=15,
            not_before=PAST,
        )


def test_find_conflicts_returns_all_overlaps():
    candidate = Interval(local(2026, 9, 15, 12), local(2026, 9, 15, 14))
    busy = [
        Interval(local(2026, 9, 15, 11), local(2026, 9, 15, 12, 30)),
        Interval(local(2026, 9, 15, 13, 30), local(2026, 9, 15, 15)),
        Interval(local(2026, 9, 15, 16), local(2026, 9, 15, 17)),
    ]
    assert len(find_conflicts(candidate, busy)) == 2


def test_is_slot_available_checks_window_boundaries(tz, work_window):
    inside = Interval(local(2026, 9, 15, 18, 0), local(2026, 9, 15, 19, 0))
    outside = Interval(local(2026, 9, 15, 18, 30), local(2026, 9, 15, 19, 30))

    assert is_slot_available(inside, windows=[work_window], busy=[], tz=tz, not_before=PAST)
    assert not is_slot_available(outside, windows=[work_window], busy=[], tz=tz, not_before=PAST)


def test_is_slot_available_rejects_past(tz, work_window):
    candidate = Interval(local(2026, 9, 15, 10, 0), local(2026, 9, 15, 11, 0))
    assert not is_slot_available(
        candidate,
        windows=[work_window],
        busy=[],
        tz=tz,
        not_before=local(2026, 9, 15, 12, 0),
    )


def test_dst_transition_day_produces_consistent_slots(tz):
    """26.10.2025 — переход на зимнее время в Кишинёве (03:00 → 02:00)."""
    slots = generate_slots(
        day=date(2025, 10, 26),
        tz=tz,
        windows=[WorkWindow(time(10, 0), time(14, 0))],
        busy=[],
        duration_minutes=60,
        step_minutes=60,
        not_before=local(2025, 10, 25, 0, 0),
    )
    assert len(slots) == 4
    assert slots[0] == local(2025, 10, 26, 10, 0)
    # После перехода на зимнее время смещение зоны одинаково для всех слотов дня.
    assert {slot.utcoffset() for slot in slots} == {timedelta(hours=2)}
    assert all(
        later - earlier == timedelta(hours=1)
        for earlier, later in pairwise(slots)
    )
