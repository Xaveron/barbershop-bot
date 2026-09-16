from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminServiceSG(StatesGroup):
    name = State()
    duration = State()
    price = State()
    description = State()


class AdminBarberSG(StatesGroup):
    name = State()
    description = State()


class AdminBranchSG(StatesGroup):
    name = State()
    address = State()


class AdminStaffSG(StatesGroup):
    telegram_id = State()


class AdminScheduleSG(StatesGroup):
    hours = State()


class AdminExceptionSG(StatesGroup):
    date = State()
    mode = State()
    hours = State()


class AdminFieldSG(StatesGroup):
    """Универсальное редактирование одного поля (контекст лежит в data)."""

    value = State()


class AdminSettingsSG(StatesGroup):
    """Настройки арендатора (Phase 9C) — отдельная группа, а не AdminFieldSG:
    у арендатора нет entity_id (арендатор один, определяется tenant_id из
    DI), а полям (timezone/currency) нужны свои валидаторы, не входящие в
    AdminFieldSG._parse_value. Плюс явный шаг подтверждения (см. Phase 9C
    §UI FLOW), которого нет у остальных однополевых правок."""

    value = State()
    confirm = State()
