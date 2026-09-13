"""Точка входа в админ-панель."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.admin import admin_menu_kb
from app.bot.keyboards.callbacks import AdmCB
from app.bot.utils import edit_message

logger = logging.getLogger(__name__)
router = Router(name="admin-menu")

ADMIN_MENU_TEXT = "🛠 <b>Админ-панель</b>\n\nВыберите раздел:"


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(ADMIN_MENU_TEXT, reply_markup=admin_menu_kb())


@router.callback_query(AdmCB.filter(F.action == "menu"))
async def open_admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_message(callback, ADMIN_MENU_TEXT, admin_menu_kb())
    await callback.answer()
