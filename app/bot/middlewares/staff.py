"""Резолвит текущего Telegram-пользователя в StaffMember его арендатора."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.repositories import StaffRepository

logger = logging.getLogger(__name__)


class StaffContextMiddleware(BaseMiddleware):
    """Ставится после UserContextMiddleware — читает data["settings"], уже
    выставленный ею, и расширяет data["is_admin"] (сегодня — только флаг
    показа кнопки «Админ-панель»), а не заменяет его. Не проверяет права:
    это делает IsStaff/RequirePermission (app/bot/middlewares/permissions.py)
    ниже по цепочке."""

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
        tenant_id = data["tenant_id"]

        staff = None
        if telegram_user is not None and not telegram_user.is_bot and session is not None:
            staff = await StaffRepository(session, tenant_id).get_by_telegram_id(telegram_user.id)
        data["staff"] = staff

        data["is_admin"] = bool(data.get("is_admin")) or bool(
            staff is not None and staff.is_active
        )
        return await handler(event, data)
