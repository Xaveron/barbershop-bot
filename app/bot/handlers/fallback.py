"""Обработка всего, что не подошло ни одному хендлеру."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.i18n import t
from app.bot.keyboards.callbacks import AdmCB, AdmDayCB
from app.bot.keyboards.client import main_menu_kb

logger = logging.getLogger(__name__)
router = Router(name="fallback")


@router.message(Command("admin"))
async def denied_admin_command(message: Message, is_admin: bool, lang: str) -> None:
    """Команда дошла сюда — значит, админ-роутер её не принял."""
    logger.warning(
        "Отказано в доступе к админ-панели: telegram_id=%s",
        message.from_user.id if message.from_user else None,
    )
    await message.answer(
        t("common.admin_only", lang),
        reply_markup=main_menu_kb(lang, is_admin=is_admin),
    )


@router.callback_query(AdmCB.filter())
@router.callback_query(AdmDayCB.filter())
async def denied_admin_callback(callback: CallbackQuery, lang: str) -> None:
    """Админ-роутер не принял событие — значит, прав недостаточно."""
    logger.warning(
        "Отказано в доступе к админ-кнопке: telegram_id=%s, data=%s",
        callback.from_user.id,
        callback.data,
    )
    await callback.answer(t("common.no_rights", lang), show_alert=True)


@router.callback_query()
async def unknown_callback(callback: CallbackQuery, lang: str) -> None:
    """Например, повторное нажатие кнопки на устаревшем сообщении."""
    await callback.answer(t("common.outdated_button", lang), show_alert=False)


@router.message()
async def unknown_message(message: Message, is_admin: bool, lang: str) -> None:
    await message.answer(
        t("common.unknown_message", lang),
        reply_markup=main_menu_kb(lang, is_admin=is_admin),
    )
