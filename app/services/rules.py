"""Доменные правила записей — чистые функции, пригодные для юнит-тестов.

Ошибки несут ключ перевода, а не готовый текст: сообщение собирается
в хендлере на языке конкретного пользователя.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.database.models import Appointment, AppointmentStatus


class RuleViolationError(Exception):
    """Нарушение доменного правила; текст безопасно показать пользователю."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def ensure_confirmed(appointment: Appointment) -> None:
    if appointment.status == AppointmentStatus.CANCELLED:
        raise RuleViolationError("rule.already_cancelled")
    if appointment.status in (AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW):
        raise RuleViolationError("rule.already_completed")


def ensure_not_started(appointment: Appointment, now: datetime) -> None:
    if appointment.starts_at <= now:
        raise RuleViolationError("rule.already_started")


def ensure_can_cancel(appointment: Appointment, now: datetime, min_lead_minutes: int) -> None:
    """Отмена возможна только для подтверждённой будущей записи не позже дедлайна."""
    ensure_confirmed(appointment)
    ensure_not_started(appointment, now)
    deadline = appointment.starts_at - timedelta(minutes=min_lead_minutes)
    if now > deadline:
        raise RuleViolationError("rule.cancel_deadline", minutes=min_lead_minutes)


def ensure_can_reschedule(appointment: Appointment, now: datetime, min_lead_minutes: int) -> None:
    ensure_confirmed(appointment)
    ensure_not_started(appointment, now)
    deadline = appointment.starts_at - timedelta(minutes=min_lead_minutes)
    if now > deadline:
        raise RuleViolationError("rule.reschedule_deadline", minutes=min_lead_minutes)


def ensure_within_limit(active_count: int, limit: int) -> None:
    if active_count >= limit:
        raise RuleViolationError("rule.limit_reached", count=active_count)
