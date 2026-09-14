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


class AdminScheduleSG(StatesGroup):
    hours = State()


class AdminExceptionSG(StatesGroup):
    date = State()
    mode = State()
    hours = State()


class AdminFieldSG(StatesGroup):
    """Универсальное редактирование одного поля (контекст лежит в data)."""

    value = State()
