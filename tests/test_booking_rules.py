"""Тесты правил отмены и переноса записей."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.database.models import Appointment, AppointmentStatus
from app.services.rules import (
    RuleViolationError,
    ensure_can_cancel,
    ensure_can_reschedule,
    ensure_confirmed,
    ensure_not_started,
    ensure_within_limit,
)
from tests.conftest import local

NOW = local(2026, 9, 15, 10, 0)


def make_appointment(
    *,
    hours_ahead: float = 24,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
    duration: int = 60,
) -> Appointment:
    start = NOW + timedelta(hours=hours_ahead)
    return Appointment(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        barber_id=uuid.uuid4(),
        service_id=uuid.uuid4(),
        starts_at=start,
        ends_at=start + timedelta(minutes=duration),
        status=status,
        price=Decimal("250.00"),
        currency="MDL",
        duration_minutes=duration,
    )


def test_confirmed_appointment_passes_checks():
    appointment = make_appointment()
    ensure_confirmed(appointment)
    ensure_not_started(appointment, NOW)
    ensure_can_cancel(appointment, NOW, 120)
    ensure_can_reschedule(appointment, NOW, 120)


def test_cancelled_appointment_cannot_be_cancelled_again():
    appointment = make_appointment(status=AppointmentStatus.CANCELLED)
    with pytest.raises(RuleViolationError):
        ensure_can_cancel(appointment, NOW, 120)


def test_completed_appointment_cannot_be_rescheduled():
    appointment = make_appointment(status=AppointmentStatus.COMPLETED)
    with pytest.raises(RuleViolationError):
        ensure_can_reschedule(appointment, NOW, 120)


def test_started_appointment_cannot_be_cancelled():
    appointment = make_appointment(hours_ahead=-1)
    with pytest.raises(RuleViolationError):
        ensure_can_cancel(appointment, NOW, 0)


def test_cancel_deadline_is_enforced():
    appointment = make_appointment(hours_ahead=1)
    with pytest.raises(RuleViolationError):
        ensure_can_cancel(appointment, NOW, 120)


def test_cancel_allowed_exactly_at_deadline():
    appointment = make_appointment(hours_ahead=2)
    ensure_can_cancel(appointment, NOW, 120)


def test_active_appointments_limit():
    ensure_within_limit(2, 3)
    with pytest.raises(RuleViolationError):
        ensure_within_limit(3, 3)
