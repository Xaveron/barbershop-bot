from __future__ import annotations

from aiogram import Router

from app.bot.handlers.admin import (
    appointments,
    barbers,
    billing,
    branches,
    editing,
    language,
    menu,
    reports,
    schedule,
    services,
    settings,
    staff,
)
from app.bot.middlewares.permissions import IsStaff


def build_admin_router() -> Router:
    """Все админ-хендлеры за общим фильтром «это вообще сотрудник арендатора
    или платформенный SUPER_ADMIN». Конкретное право на конкретный раздел
    проверяет RequirePermission на каждом под-роутере (см. docs/RBAC_DESIGN.md)."""
    router = Router(name="admin")
    router.message.filter(IsStaff())
    router.callback_query.filter(IsStaff())

    router.include_router(menu.router)
    router.include_router(services.router)
    router.include_router(barbers.router)
    router.include_router(branches.router)
    router.include_router(staff.router)
    router.include_router(settings.router)
    router.include_router(language.router)
    router.include_router(schedule.router)
    router.include_router(appointments.router)
    router.include_router(reports.router)
    router.include_router(editing.router)
    router.include_router(billing.router)
    return router


__all__ = ["build_admin_router"]
