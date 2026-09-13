from __future__ import annotations

from aiogram import Router

from app.bot.handlers.admin import (
    appointments,
    barbers,
    editing,
    menu,
    reports,
    schedule,
    services,
)
from app.bot.middlewares.admin import IsAdmin


def build_admin_router() -> Router:
    """Все админ-хендлеры за общим фильтром прав."""
    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())

    router.include_router(menu.router)
    router.include_router(services.router)
    router.include_router(barbers.router)
    router.include_router(schedule.router)
    router.include_router(appointments.router)
    router.include_router(reports.router)
    router.include_router(editing.router)
    return router


__all__ = ["build_admin_router"]
