"""Точка входа в админ-панель."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.i18n import t
from app.bot.keyboards.admin import admin_menu_kb
from app.bot.keyboards.callbacks import AdmCB
from app.bot.utils import edit_message
from app.database.models import Permission, StaffMember
from app.services.authorization import AuthorizationService

logger = logging.getLogger(__name__)
router = Router(name="admin-menu")


def _menu_kb(is_super_admin: bool, staff: StaffMember | None, lang: str):
    can_manage_branches = AuthorizationService.has_permission(
        staff, Permission.MANAGE_BRANCHES, is_super_admin=is_super_admin
    )
    can_view_staff = AuthorizationService.has_permission(
        staff, Permission.VIEW_STAFF, is_super_admin=is_super_admin
    )
    can_manage_subscription = AuthorizationService.has_permission(
        staff, Permission.MANAGE_SUBSCRIPTION, is_super_admin=is_super_admin
    )
    can_manage_settings = AuthorizationService.has_permission(
        staff, Permission.MANAGE_SETTINGS, is_super_admin=is_super_admin
    )
    return admin_menu_kb(
        lang,
        can_manage_branches=can_manage_branches,
        can_view_staff=can_view_staff,
        can_manage_subscription=can_manage_subscription,
        can_manage_settings=can_manage_settings,
    )


@router.message(Command("admin"))
async def cmd_admin(
    message: Message,
    state: FSMContext,
    is_super_admin: bool,
    staff: StaffMember | None,
    staff_lang: str,
) -> None:
    await state.clear()
    await message.answer(
        t("admin.menu.title", staff_lang), reply_markup=_menu_kb(is_super_admin, staff, staff_lang)
    )


@router.callback_query(AdmCB.filter(F.action == "menu"))
async def open_admin_menu(
    callback: CallbackQuery,
    state: FSMContext,
    is_super_admin: bool,
    staff: StaffMember | None,
    staff_lang: str,
) -> None:
    await state.clear()
    await edit_message(
        callback, t("admin.menu.title", staff_lang), _menu_kb(is_super_admin, staff, staff_lang)
    )
    await callback.answer()
