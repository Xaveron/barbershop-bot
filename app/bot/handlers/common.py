"""Старт, главное меню, помощь, выбор языка, сброс состояния."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.onboarding import render_onboarding_entry
from app.bot.i18n import LANGUAGE_NAMES, LANGUAGES, normalize_language, t
from app.bot.keyboards.callbacks import LangCB, MenuCB, NavCB
from app.bot.keyboards.client import languages_kb, main_menu_kb
from app.bot.utils import edit_message
from app.config import Settings
from app.database.models import Permission, StaffMember, TenantStatus, User
from app.database.repositories import StaffRepository, TenantRepository, UserRepository
from app.services.authorization import AuthorizationService
from app.services.onboarding import TenantOnboardingService
from app.utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user: User,
    settings: Settings,
    staff: StaffMember | None,
    is_admin: bool,
    is_super_admin: bool,
    lang: str,
) -> None:
    await state.clear()

    tenant = await TenantRepository(session).get(tenant_id)
    if tenant is not None and tenant.status != TenantStatus.ACTIVE:
        await _handle_inactive_tenant(
            message, state, session, tenant_id, staff, is_super_admin, lang
        )
        return

    await message.answer(
        t(
            "common.greeting",
            lang,
            shop=esc(settings.shop_name),
            name=esc(user.full_name.split()[0]),
        ),
        reply_markup=main_menu_kb(lang, is_admin=is_admin),
    )


async def _handle_inactive_tenant(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    lang: str,
) -> None:
    """Арендатор ещё не ACTIVE (онбординг/приостановлен): обычным клиентам —
    нейтральное сообщение без меню и без входа в запись (см.
    docs/TENANT_ONBOARDING_DESIGN.md §7), владельцу/админу арендатора —
    мастер онбординга. Платформенный оператор (Phase 8,
    data["is_super_admin"] — см. app/services/platform_authorization.py),
    если у арендатора ещё нет ни одного сотрудника, становится TENANT_OWNER
    здесь же — единственный временный мост через платформенную идентичность
    (см. docs/PLATFORM_CONTROL_PLANE.md)."""
    telegram_id = message.from_user.id if message.from_user else None
    can_manage_tenant = AuthorizationService.has_permission(
        staff, Permission.MANAGE_TENANT, is_super_admin=is_super_admin
    )

    if not can_manage_tenant and is_super_admin and telegram_id is not None:
        staff_repo = StaffRepository(session, tenant_id)
        if not await staff_repo.has_any_staff():
            await TenantOnboardingService(session, tenant_id).ensure_owner(
                telegram_id=telegram_id, actor_telegram_id=telegram_id
            )
            await message.answer(t("onboarding.owner_claimed", lang))
            can_manage_tenant = True

    if can_manage_tenant:
        await render_onboarding_entry(message, state, session, tenant_id, lang)
        return

    await message.answer(t("onboarding.not_active_customer", lang))


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
    is_admin: bool,
    tenant_default_language: str,
) -> None:
    chosen = normalize_language(callback_data.code, tenant_default_language)
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
