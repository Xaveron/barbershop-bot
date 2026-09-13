from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BookingSG(StatesGroup):
    """Услуга → Барбер → Дата → Время → (Телефон) → Подтверждение."""

    service = State()
    barber = State()
    day = State()
    time = State()
    phone = State()
    confirm = State()


class RescheduleSG(StatesGroup):
    """Перенос существующей записи (клиентом или администратором)."""

    day = State()
    time = State()
    confirm = State()
