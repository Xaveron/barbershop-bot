from __future__ import annotations

from aiogram import Router

from app.bot.handlers import appointments, booking, common, errors, fallback, info, onboarding
from app.bot.handlers.admin import build_admin_router
from app.bot.handlers.platform import build_platform_router


def build_router() -> Router:
    """Корневой роутер. Порядок важен: fallback подключается последним.

    platform-роутер безопасно живёт в том же дереве, что и все
    tenant-роутеры: RequirePlatformOperator (см.
    app/bot/middlewares/permissions.py) пропускает только апдейты от
    выделенного платформенного бота, поэтому обычный бот арендатора никогда
    до него не доходит (см. docs/PLATFORM_CONTROL_PLANE.md)."""
    router = Router(name="root")
    router.include_router(errors.router)
    router.include_router(build_platform_router())
    router.include_router(common.router)
    router.include_router(onboarding.router)
    router.include_router(build_admin_router())
    router.include_router(booking.router)
    router.include_router(appointments.router)
    router.include_router(info.router)
    router.include_router(fallback.router)
    return router


__all__ = ["build_router"]
