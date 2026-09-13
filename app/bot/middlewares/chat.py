"""Бот работает только в личных чатах.

В группе кнопки и карточки записей видны всем участникам, а нажать их может
любой — это утечка персональных данных клиента. Поэтому апдейты из групп,
супергрупп и каналов не доходят ни до базы, ни до хендлеров.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Chat, Message, TelegramObject, Update

from app.bot.i18n import normalize_language, t

logger = logging.getLogger(__name__)

class PrivateChatOnlyMiddleware(BaseMiddleware):
    def __init__(self, default_language: str = "ru") -> None:
        self.default_language = default_language

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat: Chat | None = data.get("event_chat")
        if chat is None or chat.type == ChatType.PRIVATE:
            return await handler(event, data)

        logger.info("Апдейт из чата типа %s проигнорирован", chat.type)
        inner = event.message if isinstance(event, Update) else None
        if isinstance(inner, Message) and inner.text and inner.text.startswith("/"):
            # Отвечаем только на команды, чтобы не спамить в чате обычными сообщениями.
            lang = normalize_language(
                inner.from_user.language_code if inner.from_user else None,
                self.default_language,
            )
            await inner.answer(t("common.private_only", lang))
        return None
