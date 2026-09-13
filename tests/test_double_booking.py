"""Тесты предотвращения двойного бронирования и пересечения записей."""

from __future__ import annotations

import uuid
from datetime import date, time

from app.services.booking import _advisory_lock_key
from app.services.slots import (
    Interval,
    WorkWindow,
    find_conflicts,
    generate_slots,
    is_slot_available,
)
from tests.conftest import local

WINDOW = WorkWindow(time(10, 0), time(18, 0))
DAY = date(2026, 9, 15)
PAST = local(2026, 9, 1, 0, 0)


def free_slots(busy, duration=60, step=30):
    return generate_slots(
        day=DAY,
        tz=local(2026, 9, 15, 10).tzinfo,
        windows=[WINDOW],
        busy=busy,
        duration_minutes=duration,
        step_minutes=step,
        not_before=PAST,
    )


def test_second_client_cannot_take_taken_slot(tz):
    """Первый клиент занял 12:00–13:00 — слот исчезает из выдачи."""
    before = free_slots([])
    assert local(2026, 9, 15, 12, 0) in before

    booked = [Interval(local(2026, 9, 15, 12, 0), local(2026, 9, 15, 13, 0))]
    after = free_slots(booked)
    assert local(2026, 9, 15, 12, 0) not in after

    candidate = Interval(local(2026, 9, 15, 12, 0), local(2026, 9, 15, 13, 0))
    assert not is_slot_available(
        candidate, windows=[WINDOW], busy=booked, tz=tz, not_before=PAST
    )


def test_partial_overlap_is_rejected(tz):
    booked = [Interval(local(2026, 9, 15, 12, 0), local(2026, 9, 15, 13, 0))]
    partial = Interval(local(2026, 9, 15, 12, 30), local(2026, 9, 15, 13, 30))
    assert find_conflicts(partial, booked)
    assert not is_slot_available(partial, windows=[WINDOW], busy=booked, tz=tz, not_before=PAST)


def test_long_service_cannot_fit_between_bookings(tz):
    busy = [
        Interval(local(2026, 9, 15, 11, 0), local(2026, 9, 15, 12, 0)),
        Interval(local(2026, 9, 15, 13, 0), local(2026, 9, 15, 14, 0)),
    ]
    ninety_minutes = free_slots(busy, duration=90, step=30)
    assert local(2026, 9, 15, 12, 0) not in ninety_minutes
    sixty_minutes = free_slots(busy, duration=60, step=30)
    assert local(2026, 9, 15, 12, 0) in sixty_minutes


def test_back_to_back_bookings_are_allowed(tz):
    busy = [Interval(local(2026, 9, 15, 11, 0), local(2026, 9, 15, 12, 0))]
    candidate = Interval(local(2026, 9, 15, 12, 0), local(2026, 9, 15, 13, 0))
    assert is_slot_available(candidate, windows=[WINDOW], busy=busy, tz=tz, not_before=PAST)


def test_rescheduling_ignores_own_interval(tz):
    """При переносе собственная запись исключается из занятых интервалов."""
    own = Interval(local(2026, 9, 15, 12, 0), local(2026, 9, 15, 13, 0))
    others = []
    candidate = Interval(local(2026, 9, 15, 12, 30), local(2026, 9, 15, 13, 30))
    assert not is_slot_available(candidate, windows=[WINDOW], busy=[own], tz=tz, not_before=PAST)
    assert is_slot_available(candidate, windows=[WINDOW], busy=others, tz=tz, not_before=PAST)


def test_advisory_lock_key_is_stable_and_bigint():
    barber_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    key = _advisory_lock_key(barber_id)
    assert key == _advisory_lock_key(barber_id)
    assert -(2**63) <= key < 2**63
    assert key != _advisory_lock_key(uuid.uuid4())
