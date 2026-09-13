"""Глобальный обработчик исключений."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ErrorEvent

from app.bot.i18n import normalize_language, t

logger = logging.getLogger(__name__)
router = Router(name="errors")


@router.errors()
async def handle_error(event: ErrorEvent) -> bool:
    exception = event.exception

    if isinstance(exception, TelegramRetryAfter):
        logger.warning("Telegram flood control: %s c", exception.retry_after)
        return True
    if isinstance(exception, TelegramForbiddenError):
        logger.info("Пользователь заблокировал бота")
        return True
    if isinstance(exception, TelegramBadRequest) and "message is not modified" in str(exception):
        return True

    logger.exception("Необработанная ошибка при обработке апдейта", exc_info=exception)

    callback = event.update.callback_query
    if callback is not None:
        try:
            lang = normalize_language(callback.from_user.language_code)
            await callback.answer(t("common.error_alert", lang), show_alert=True)
        except Exception:
            logger.debug("Не удалось ответить на callback после ошибки")
        return True

    message = event.update.message
    if message is not None:
        try:
            lang = normalize_language(
                message.from_user.language_code if message.from_user else None
            )
            await message.answer(t("common.error_message", lang))
        except Exception:
            logger.debug("Не удалось отправить сообщение об ошибке")
    return True
