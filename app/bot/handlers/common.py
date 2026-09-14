"""Старт, главное меню, помощь, выбор языка, сброс состояния."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import LANGUAGE_NAMES, LANGUAGES, normalize_language, t
from app.bot.keyboards.callbacks import LangCB, MenuCB, NavCB
from app.bot.keyboards.client import languages_kb, main_menu_kb
from app.bot.utils import edit_message
from app.config import Settings
from app.database.models import User
from app.database.repositories import UserRepository
from app.utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user: User,
    settings: Settings,
    is_admin: bool,
    lang: str,
) -> None:
    await state.clear()
    await message.answer(
        t(
            "common.greeting",
            lang,
            shop=esc(settings.shop_name),
            name=esc(user.full_name.split()[0]),
        ),
        reply_markup=main_menu_kb(lang, is_admin=is_admin),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, is_admin: bool, lang: str) -> None:
    await message.answer(
        t("common.help", lang), reply_markup=main_menu_kb(lang, is_admin=is_admin)
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, is_admin: bool, lang: str) -> None:
    await state.clear()
    await message.answer(
        f"{t('common.action_cancelled', lang)}\n\n{t('common.main_menu', lang)}",
        reply_markup=main_menu_kb(lang, is_admin=is_admin),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, is_admin: bool, lang: str) -> None:
    await state.clear()
    await message.answer(
        t("common.main_menu", lang), reply_markup=main_menu_kb(lang, is_admin=is_admin)
    )


@router.callback_query(NavCB.filter(F.to == "main"))
@router.callback_query(MenuCB.filter(F.action == "main"))
async def back_to_main(
    callback: CallbackQuery, state: FSMContext, is_admin: bool, lang: str
) -> None:
    await state.clear()
    await edit_message(callback, t("common.main_menu", lang), main_menu_kb(lang, is_admin=is_admin))
    await callback.answer()


# --- Язык -------------------------------------------------------------------
@router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer(t("language.choose", lang), reply_markup=languages_kb(lang, lang))


@router.callback_query(MenuCB.filter(F.action == "language"))
async def open_language(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    await edit_message(callback, t("language.choose", lang), languages_kb(lang, lang))
    await callback.answer()


@router.callback_query(LangCB.filter())
async def choose_language(
    callback: CallbackQuery,
    callback_data: LangCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user: User,
    settings: Settings,
    is_admin: bool,
) -> None:
    chosen = normalize_language(callback_data.code, settings.default_language)
    if callback_data.code not in LANGUAGES:
        logger.info("Неизвестный код языка в callback: %s", callback_data.code)
    await UserRepository(session, tenant_id).set_language(user, chosen)
    await session.commit()

    await edit_message(
        callback,
        t("language.saved", chosen, language=LANGUAGE_NAMES[chosen])
        + "\n\n"
        + t("common.main_menu", chosen),
        main_menu_kb(chosen, is_admin=is_admin),
    )
    await callback.answer()
