"""Админ: управление филиалами (создание, редактирование, скрытие — без удаления)."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.billing_ui import describe_billing_error
from app.bot.i18n import t
from app.bot.keyboards.admin import admin_branch_kb, admin_branches_kb, back_to_admin_kb
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import AdminBranchSG, AdminFieldSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.database.models import Branch, LimitKey, Permission
from app.database.repositories import BranchRepository
from app.services.billing import BillingError, LimitService
from app.services.provisioning import BranchProvisioningService
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_description, validate_name

logger = logging.getLogger(__name__)
router = Router(name="admin-branches")
router.message.filter(RequirePermission(Permission.MANAGE_BRANCHES))
router.callback_query.filter(RequirePermission(Permission.MANAGE_BRANCHES))

PAGE_SIZE = 8


def branch_card(branch: Branch, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    status = (
        t("admin.branch.status_active", lang)
        if branch.is_active
        else t("admin.branch.status_hidden", lang)
    )
    text = (
        f"📍 <b>{esc(branch.name)}</b>\n\n"
        f"📝 {esc(branch.address or '—')}\n"
        f"{t('admin.branch.card_status', lang, status=status)}"
    )
    return text, admin_branch_kb(branch, lang)


async def branches_list(
    session: AsyncSession, tenant_id: uuid.UUID, lang: str, page: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    """Пагинированный admin-список (см. Phase 9C §M-6) — отдельно от
    BranchRepository.list_active(), которым продолжают пользоваться
    operational-пикеры (schedule/exceptions/booking): им нужны ВСЕ активные
    филиалы разом, а не одна страница."""
    repository = BranchRepository(session, tenant_id)
    total = await repository.count_all()
    branches = await repository.list_all(limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    if not branches and page > 0:
        return await branches_list(session, tenant_id, lang, 0)
    if not branches:
        return t("admin.branches.empty", lang), admin_branches_kb(branches, lang, page, False)
    lines = [t("admin.branches.list_title", lang, total=total) + "\n"]
    for branch in branches:
        lines.append(f"{'✅' if branch.is_active else '🚫'} {esc(branch.name)}")
    has_next = (page + 1) * PAGE_SIZE < total
    return "\n".join(lines), admin_branches_kb(branches, lang, page, has_next)


@router.callback_query(AdmCB.filter(F.action == "branches"))
async def show_branches(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    text, markup = await branches_list(session, tenant_id, staff_lang, page)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brh"))
async def show_branch(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    branch = await _get_branch(callback_data.arg, session, tenant_id)
    if branch is None:
        await alert(callback, t("admin.branch.not_found", staff_lang))
        return
    text, markup = branch_card(branch, staff_lang)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brh_add"))
async def add_branch_start(callback: CallbackQuery, state: FSMContext, staff_lang: str) -> None:
    await state.clear()
    await state.set_state(AdminBranchSG.name)
    await edit_message(
        callback,
        t("admin.branch.add_title", staff_lang),
        back_to_admin_kb(staff_lang, "branches"),
    )
    await callback.answer()


@router.message(AdminBranchSG.name)
async def add_branch_name(message: Message, state: FSMContext, staff_lang: str) -> None:
    try:
        name = validate_name(
            message.text or "", lang=staff_lang, field=t("admin.settings.field_name", staff_lang)
        )
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(name=name)
    await state.set_state(AdminBranchSG.address)
    await message.answer(t("admin.branch.add_step2", staff_lang))


@router.message(AdminBranchSG.address)
async def add_branch_address(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    try:
        address = validate_description(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    data = await state.get_data()
    await state.clear()
    try:
        branch = await BranchProvisioningService(session, tenant_id).create_branch(
            name=data["name"], address=address
        )
        await session.commit()
    except BillingError as exc:
        await session.rollback()
        await message.answer(f"⚠️ {describe_billing_error(exc, staff_lang)}")
        return
    except Exception:
        await session.rollback()
        logger.exception("Не удалось создать филиал")
        await message.answer(t("admin.branch.create_failed", staff_lang))
        return
    text, markup = branch_card(branch, staff_lang)
    await message.answer(t("admin.branch.created", staff_lang) + text, reply_markup=markup)


_FIELD_PROMPT_KEYS = {
    "brh_name": ("name", "admin.branch.prompt_name"),
    "brh_addr": ("address", "admin.branch.prompt_address"),
}


@router.callback_query(AdmCB.filter(F.action.in_(set(_FIELD_PROMPT_KEYS))))
async def edit_branch_field(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    branch = await _get_branch(callback_data.arg, session, tenant_id)
    if branch is None:
        await alert(callback, t("admin.branch.not_found", staff_lang))
        return
    field, prompt_key = _FIELD_PROMPT_KEYS[callback_data.action]
    await state.set_state(AdminFieldSG.value)
    await state.update_data(entity="branch", field=field, entity_id=str(branch.id))
    await edit_message(
        callback,
        t(
            "admin.common.edit_field_prompt",
            staff_lang,
            name=esc(branch.name),
            prompt=t(prompt_key, staff_lang),
            cancel_hint=t("admin.common.cancel_hint", staff_lang),
        ),
        back_to_admin_kb(staff_lang, "brh", str(branch.id)),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brh_toggle"))
async def toggle_branch(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    branch = await _get_branch(callback_data.arg, session, tenant_id)
    if branch is None:
        await alert(callback, t("admin.branch.not_found", staff_lang))
        return
    if not branch.is_active:
        # Реактивация — на один активный ресурс больше, проверяется тем же
        # LimitService.assert_can_create, что и создание нового филиала (см.
        # Phase 9B §M-2, тот же паттерн уже применён к барберам/услугам в
        # admin/barbers.py::toggle_barber и admin/services.py::toggle_service):
        # нельзя обойти MAX_BRANCHES циклом скрыть→создать→показать. Найдено
        # и исправлено по ходу Phase 9G — этот путь был единственным из трёх
        # toggle-хендлеров без проверки лимита при реактивации.
        try:
            await LimitService(session, tenant_id).assert_can_create(LimitKey.MAX_BRANCHES)
        except BillingError as exc:
            await session.rollback()
            await alert(callback, describe_billing_error(exc, staff_lang))
            return
    branch.is_active = not branch.is_active
    await session.commit()
    text, markup = branch_card(branch, staff_lang)
    await edit_message(callback, text, markup)
    await callback.answer(t("admin.common.status_updated", staff_lang))


async def _get_branch(raw_id: str, session: AsyncSession, tenant_id: uuid.UUID) -> Branch | None:
    branch_id = parse_uuid(raw_id)
    if branch_id is None:
        return None
    return await BranchRepository(session, tenant_id).get(branch_id)
