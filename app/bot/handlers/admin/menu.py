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
from app.config import Settings
from app.database.models import Permission, StaffMember
from app.services.authorization import AuthorizationService

logger = logging.getLogger(__name__)
router = Router(name="admin-menu")

ADMIN_MENU_TEXT = "🛠 <b>Админ-панель</b>\n\nВыберите раздел:"


def _menu_kb(is_super_admin: bool, staff: StaffMember | None):
    can_manage_branches = AuthorizationService.has_permission(
        staff, Permission.MANAGE_BRANCHES, is_super_admin=is_super_admin
    )
    can_view_staff = AuthorizationService.has_permission(
        staff, Permission.VIEW_STAFF, is_super_admin=is_super_admin
    )
    return admin_menu_kb(can_manage_branches=can_manage_branches, can_view_staff=can_view_staff)


@router.message(Command("admin"))
async def cmd_admin(
    message: Message, state: FSMContext, settings: Settings, staff: StaffMember | None
) -> None:
    await state.clear()
    is_super_admin = bool(message.from_user and settings.is_admin(message.from_user.id))
    await message.answer(ADMIN_MENU_TEXT, reply_markup=_menu_kb(is_super_admin, staff))


@router.callback_query(AdmCB.filter(F.action == "menu"))
async def open_admin_menu(
    callback: CallbackQuery, state: FSMContext, settings: Settings, staff: StaffMember | None
) -> None:
    await state.clear()
    is_super_admin = bool(callback.from_user and settings.is_admin(callback.from_user.id))
    await edit_message(callback, ADMIN_MENU_TEXT, _menu_kb(is_super_admin, staff))
    await callback.answer()
