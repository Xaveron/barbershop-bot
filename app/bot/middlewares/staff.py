"""Резолвит текущего Telegram-пользователя в StaffMember его арендатора."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import FALLBACK_LANGUAGE
from app.config import Settings
from app.database.repositories import StaffRepository
from app.services.locale import resolve_staff_locale
from app.services.platform_authorization import PlatformAuthorizationService

logger = logging.getLogger(__name__)


class StaffContextMiddleware(BaseMiddleware):
    """Ставится после UserContextMiddleware — читает data["settings"], уже
    выставленный ею, и расширяет data["is_admin"] (сегодня — только флаг
    показа кнопки «Админ-панель»), а не заменяет его. Не проверяет права:
    это делает IsStaff/RequirePermission (app/bot/middlewares/permissions.py)
    ниже по цепочке.

    Phase 8: здесь же, один раз на апдейт, резолвится data["is_super_admin"] —
    платформенная авторизация (PlatformAuthorizationService), а не
    settings.is_admin(...) инлайн в каждом хендлере (см.
    docs/PLATFORM_CONTROL_PLANE.md). tenant_id может быть None (апдейт от
    платформенного бота, см. app/bot/middlewares/bot_identity.py) — тогда
    искать StaffMember негде, но платформенная проверка всё равно нужна."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user: TelegramUser | None = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")
        tenant_id = data.get("tenant_id")

        staff = None
        is_super_admin = False
        if telegram_user is not None and not telegram_user.is_bot and session is not None:
            if tenant_id is not None:
                staff = await StaffRepository(session, tenant_id).get_by_telegram_id(
                    telegram_user.id
                )
            is_super_admin = await PlatformAuthorizationService(
                session, self.settings
            ).is_operator(telegram_user.id)
        data["staff"] = staff
        data["is_super_admin"] = is_super_admin
        # Язык персонала (Phase 9E §6) — StaffMember.language -> Tenant.
        # default_language -> FALLBACK_LANGUAGE, НИКОГДА не data["lang"]
        # (тот резолвится из User.language_code клиента — см.
        # UserContextMiddleware — разные оси персонажей, разные ключи).
        data["staff_lang"] = resolve_staff_locale(
            staff, data.get("tenant_default_language", FALLBACK_LANGUAGE)
        )

        data["is_admin"] = (
            bool(data.get("is_admin"))
            or bool(staff is not None and staff.is_active)
            or is_super_admin
        )
        return await handler(event, data)
