from __future__ import annotations

from aiogram import Router

from app.bot.handlers.platform import bots, menu


def build_platform_router() -> Router:
    """Все платформенные хендлеры за RequirePlatformOperator (проверяется на
    каждом под-роутере отдельно — см. docs/PLATFORM_CONTROL_PLANE.md).
    Апдейт от обычного бота арендатора никогда не пройдёт этот фильтр:
    is_platform_bot выставляется только BotIdentityMiddleware для
    сконфигурированного PLATFORM_BOT_TOKEN."""
    router = Router(name="platform")
    router.include_router(menu.router)
    router.include_router(bots.router)
    return router


__all__ = ["build_platform_router"]
