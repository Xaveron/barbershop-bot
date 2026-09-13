"""Страховка на исходящих запросах к Telegram Bot API.

Регистрируется на сессии бота (`bot.session.middleware(...)`), поэтому
работает для всех отправок — из хендлеров, из планировщика и из сервисов.
Задача одна: не дать боту упасть на лимитах Telegram, если список услуг,
клиентов или записей вырос больше ожидаемого.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot
from aiogram.methods import TelegramMethod

from app.utils.text import TELEGRAM_CAPTION_LIMIT, TELEGRAM_TEXT_LIMIT, clip

logger = logging.getLogger(__name__)

# Лимиты Telegram на всплывающие ответы к нажатию кнопки.
CALLBACK_ANSWER_LIMIT = 200


class TextLimitMiddleware:
    """Обрезает слишком длинный текст, сохраняя корректность HTML-разметки."""

    async def __call__(
        self,
        make_request: Callable[[Bot, TelegramMethod[Any]], Awaitable[Any]],
        bot: Bot,
        method: TelegramMethod[Any],
    ) -> Any:
        self._clip_field(method, "text", self._limit_for(method))
        self._clip_field(method, "caption", TELEGRAM_CAPTION_LIMIT)
        return await make_request(bot, method)

    @staticmethod
    def _limit_for(method: TelegramMethod[Any]) -> int:
        if type(method).__name__ == "AnswerCallbackQuery":
            return CALLBACK_ANSWER_LIMIT
        return TELEGRAM_TEXT_LIMIT

    @staticmethod
    def _clip_field(method: TelegramMethod[Any], field: str, limit: int) -> None:
        value = getattr(method, field, None)
        if not isinstance(value, str) or len(value) <= limit:
            return
        logger.warning(
            "Текст %s.%s длиной %s символов обрезан до %s",
            type(method).__name__,
            field,
            len(value),
            limit,
        )
        object.__setattr__(method, field, clip(value, limit))
