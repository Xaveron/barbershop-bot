from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class OnboardingSG(StatesGroup):
    """Мастер настройки нового арендатора (Phase 5). Каждый шаг сохраняет
    сразу в БД через существующие репозитории — FSM хранит только то, что
    ещё не отправлено (см. docs/TENANT_ONBOARDING_DESIGN.md §5)."""

    business_name = State()
    branch_name = State()
    branch_timezone = State()
    branch_currency = State()
    service_name = State()
    service_duration = State()
    service_price = State()
    barber_name = State()
    schedule_hours = State()
