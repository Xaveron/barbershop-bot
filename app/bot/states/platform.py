from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class PlatformSG(StatesGroup):
    """Создание арендатора: платформа спрашивает только название (см.
    docs/PLATFORM_CONTROL_PLANE.md §14 — слаг подбирается автоматически)."""

    tenant_name = State()
