"""Мелкие помощники для хендлеров."""

from __future__ import annotations

import logging
import uuid

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


def parse_uuid(value: str) -> uuid.UUID | None:
    """Безопасный разбор UUID из callback_data."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


async def edit_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    disable_preview: bool = True,
) -> None:
    """Редактирует сообщение, аккуратно обрабатывая повторные нажатия."""
    message = callback.message
    if not isinstance(message, Message):
        if callback.from_user is not None and callback.bot is not None:
            await callback.bot.send_message(
                callback.from_user.id, text, reply_markup=reply_markup
            )
        return
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            link_preview_options=None if not disable_preview else _no_preview(),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        logger.debug("Не удалось отредактировать сообщение: %s", exc)
        await message.answer(text, reply_markup=reply_markup)


def _no_preview():
    from aiogram.types import LinkPreviewOptions

    return LinkPreviewOptions(is_disabled=True)


async def alert(callback: CallbackQuery, text: str) -> None:
    await callback.answer(text[:200], show_alert=True)
