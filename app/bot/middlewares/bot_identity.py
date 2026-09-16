"""Bot identity -> tenant, заново на каждый апдейт (Phase 7).

Ставится ПОСЛЕ DatabaseMiddleware (нужна data["session"]) и ДО
UserContextMiddleware (которая уже читает data["tenant_id"]). Заменяет собой
process-global tenant_id, который раньше выставлялся один раз при старте
процесса в dispatcher["tenant_id"] (aiogram workflow data — одинаков для
каждого апдейта вне зависимости от бота). Никакого fallback на дефолтного
арендатора: неизвестный или отключённый bot не должен доходить до хендлеров
(см. docs/BOT_IDENTITY_ARCHITECTURE.md).

Phase 8: выделенный платформенный бот (settings.platform_bot_token) —
единственное исключение из резолюции через TelegramBotIdentity. Он не
принадлежит ни одному арендатору: для него data["tenant_id"] остаётся None,
а data["is_platform_bot"] = True — обычный tenant-бот НЕ может "стать"
платформенным (см. docs/PLATFORM_CONTROL_PLANE.md §Platform bot vs tenant bot)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import FALLBACK_LANGUAGE
from app.services.bot_identity import BotIdentityResolver
from app.services.locale import get_tenant_default_language

logger = logging.getLogger(__name__)


class BotIdentityMiddleware(BaseMiddleware):
    def __init__(self, platform_bot_id: int | None = None) -> None:
        self.platform_bot_id = platform_bot_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot: Bot = data["bot"]

        if self.platform_bot_id is not None and bot.id == self.platform_bot_id:
            data["is_platform_bot"] = True
            data["tenant_id"] = None
            # Платформенный бот не принадлежит ни одному арендатору — дефолт
            # языка тут ровно FALLBACK_LANGUAGE, никакой Tenant не читаем
            # (см. Phase 9E §17: платформенная локализация — вне этой фазы).
            data["tenant_default_language"] = FALLBACK_LANGUAGE
            return await handler(event, data)

        data["is_platform_bot"] = False
        session: AsyncSession = data["session"]
        identity = await BotIdentityResolver(session).resolve(bot.id)
        if identity is None:
            logger.warning("Апдейт от неизвестного bot_id=%s отклонён", bot.id)
            return None
        if not identity.is_active:
            logger.warning("Апдейт от отключённого bot_id=%s отклонён", bot.id)
            return None

        data["tenant_id"] = identity.tenant_id
        # Резолвится один раз на апдейт здесь (а не отдельно в
        # UserContextMiddleware и StaffContextMiddleware) — единственный
        # запрос Tenant.default_language, переиспользуемый обеими цепочками
        # резолюции языка (см. app/services/locale.py, Phase 9E §6).
        data["tenant_default_language"] = await get_tenant_default_language(
            session, identity.tenant_id
        )
        return await handler(event, data)
