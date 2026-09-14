"""Простая защита от флуда и повторных нажатий (token bucket в памяти)."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.bot.i18n import normalize_language, t

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        interval: float = 0.4,
        burst: int = 10,
        window: float = 3.0,
        default_language: str = "ru",
    ) -> None:
        self.default_language = default_language
        self.interval = interval
        self.burst = burst
        self.window = window
        self._events: defaultdict[int, deque[float]] = defaultdict(deque)
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        # Middleware зарегистрирована на уровне Update, поэтому реальное
        # событие (сообщение или нажатие кнопки) достаём из апдейта —
        # иначе пользователь не получил бы обратной связи при троттлинге.
        inner: TelegramObject = event
        if isinstance(event, Update):
            inner = event.callback_query or event.message or event

        now = time.monotonic()
        history = self._events[user.id]
        while history and now - history[0] > self.window:
            history.popleft()

        too_fast = now - self._last.get(user.id, 0.0) < self.interval
        too_many = len(history) >= self.burst
        history.append(now)
        self._last[user.id] = now
        self._prune(now)

        if too_fast or too_many:
            logger.debug("Троттлинг пользователя %s", user.id)
            lang = normalize_language(user.language_code, self.default_language)
            if isinstance(inner, CallbackQuery):
                await inner.answer(t("common.too_fast", lang), show_alert=False)
            elif isinstance(inner, Message) and too_many:
                await inner.answer(t("common.too_many_messages", lang))
            return None

        return await handler(event, data)

    def _prune(self, now: float) -> None:
        """Не даём словарям расти бесконечно."""
        if len(self._events) < 500:
            return
        stale = [uid for uid, seen in self._last.items() if now - seen > 300]
        for uid in stale:
            self._events.pop(uid, None)
            self._last.pop(uid, None)
