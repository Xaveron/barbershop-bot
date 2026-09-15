"""Bot identity -> tenant, заново на каждый апдейт (Phase 7).

Ставится ПОСЛЕ DatabaseMiddleware (нужна data["session"]) и ДО
UserContextMiddleware (которая уже читает data["tenant_id"]). Заменяет собой
process-global tenant_id, который раньше выставлялся один раз при старте
процесса в dispatcher["tenant_id"] (aiogram workflow data — одинаков для
каждого апдейта вне зависимости от бота). Никакого fallback на дефолтного
арендатора: неизвестный или отключённый bot не должен доходить до хендлеров
(см. docs/BOT_IDENTITY_ARCHITECTURE.md)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.bot_identity import BotIdentityResolver

logger = logging.getLogger(__name__)


class BotIdentityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot: Bot = data["bot"]
        session: AsyncSession = data["session"]

        identity = await BotIdentityResolver(session).resolve(bot.id)
        if identity is None:
            logger.warning("Апдейт от неизвестного bot_id=%s отклонён", bot.id)
            return None
        if not identity.is_active:
            logger.warning("Апдейт от отключённого bot_id=%s отклонён", bot.id)
            return None

        data["tenant_id"] = identity.tenant_id
        return await handler(event, data)
