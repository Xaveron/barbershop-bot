"""Регистрация пользователя и флаг администратора в контексте хендлеров."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import normalize_language
from app.config import Settings
from app.database.repositories import UserRepository

logger = logging.getLogger(__name__)


class UserContextMiddleware(BaseMiddleware):
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
        # Апдейт от платформенного бота (Phase 8) не резолвит tenant_id —
        # для него ниже по цепочке нет ни User, ни StaffMember, только
        # платформенная авторизация (см. StaffContextMiddleware).
        tenant_id = data.get("tenant_id")

        data["settings"] = self.settings
        # Финальное значение — за StaffContextMiddleware (учитывает staff и
        # платформенного оператора); здесь только безопасный дефолт.
        data["is_admin"] = False
        # Язык до обращения к БД — он нужен даже там, где пользователя нет
        # (групповые чаты, троттлинг, ошибки).
        data["lang"] = normalize_language(
            telegram_user.language_code if telegram_user else None,
            self.settings.default_language,
        )

        if (
            telegram_user is not None
            and not telegram_user.is_bot
            and session is not None
            and tenant_id is not None
        ):
            repository = UserRepository(session, tenant_id)
            user = await repository.get_or_create(
                telegram_id=telegram_user.id,
                full_name=telegram_user.full_name[:255],
                username=telegram_user.username,
                language_code=normalize_language(
                    telegram_user.language_code, self.settings.default_language
                ),
            )
            await session.commit()
            data["user"] = user
            data["lang"] = normalize_language(
                user.language_code, self.settings.default_language
            )

        return await handler(event, data)
