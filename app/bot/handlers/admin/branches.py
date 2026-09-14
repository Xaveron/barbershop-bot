"""Админ: управление филиалами (создание, редактирование, скрытие — без удаления)."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import admin_branch_kb, admin_branches_kb, back_to_admin_kb
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import AdminBranchSG, AdminFieldSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.database.models import Branch, Permission
from app.database.repositories import BranchRepository
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_description, validate_name

logger = logging.getLogger(__name__)
router = Router(name="admin-branches")
router.message.filter(RequirePermission(Permission.MANAGE_BRANCHES))
router.callback_query.filter(RequirePermission(Permission.MANAGE_BRANCHES))


def branch_card(branch: Branch) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        f"📍 <b>{esc(branch.name)}</b>\n\n"
        f"📝 {esc(branch.address or '—')}\n"
        f"👁 Статус: {'активен' if branch.is_active else 'скрыт'}"
    )
    return text, admin_branch_kb(branch)


async def branches_list(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[str, InlineKeyboardMarkup]:
    branches = await BranchRepository(session, tenant_id).list_all()
    if not branches:
        return "📍 Филиалов пока нет. Добавьте первый.", admin_branches_kb(branches)
    lines = ["📍 <b>Филиалы</b>\n"]
    for branch in branches:
        lines.append(f"{'✅' if branch.is_active else '🚫'} {esc(branch.name)}")
    return "\n".join(lines), admin_branches_kb(branches)


@router.callback_query(AdmCB.filter(F.action == "branches"))
async def show_branches(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    await state.clear()
    text, markup = await branches_list(session, tenant_id)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brh"))
async def show_branch(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    await state.clear()
    branch = await _get_branch(callback_data.arg, session, tenant_id)
    if branch is None:
        await alert(callback, "Филиал не найден.")
        return
    text, markup = branch_card(branch)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brh_add"))
async def add_branch_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminBranchSG.name)
    await edit_message(
        callback,
        "➕ <b>Новый филиал</b>\n\nШаг 1/2. Отправьте название филиала.\nДля отмены: /cancel",
        back_to_admin_kb("branches"),
    )
    await callback.answer()


@router.message(AdminBranchSG.name)
async def add_branch_name(message: Message, state: FSMContext) -> None:
    try:
        name = validate_name(message.text or "", field="Название")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(name=name)
    await state.set_state(AdminBranchSG.address)
    await message.answer("Шаг 2/2. Адрес филиала (или «-», чтобы пропустить)")


@router.message(AdminBranchSG.address)
async def add_branch_address(
    message: Message, state: FSMContext, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    try:
        address = validate_description(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    data = await state.get_data()
    await state.clear()
    try:
        branch = await BranchRepository(session, tenant_id).create(
            name=data["name"], address=address
        )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось создать филиал")
        await message.answer("⚠️ Не удалось создать филиал.")
        return
    text, markup = branch_card(branch)
    await message.answer("✅ Филиал создан.\n\n" + text, reply_markup=markup)


_FIELD_PROMPTS = {
    "brh_name": ("name", "Отправьте новое название филиала."),
    "brh_addr": ("address", "Отправьте новый адрес (или «-», чтобы очистить)."),
}


@router.callback_query(AdmCB.filter(F.action.in_(set(_FIELD_PROMPTS))))
async def edit_branch_field(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    branch = await _get_branch(callback_data.arg, session, tenant_id)
    if branch is None:
        await alert(callback, "Филиал не найден.")
        return
    field, prompt = _FIELD_PROMPTS[callback_data.action]
    await state.set_state(AdminFieldSG.value)
    await state.update_data(entity="branch", field=field, entity_id=str(branch.id))
    await edit_message(
        callback,
        f"✏️ {esc(branch.name)}\n\n{prompt}\n\nДля отмены: /cancel",
        back_to_admin_kb("brh", str(branch.id)),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brh_toggle"))
async def toggle_branch(
    callback: CallbackQuery, callback_data: AdmCB, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    branch = await _get_branch(callback_data.arg, session, tenant_id)
    if branch is None:
        await alert(callback, "Филиал не найден.")
        return
    branch.is_active = not branch.is_active
    await session.commit()
    text, markup = branch_card(branch)
    await edit_message(callback, text, markup)
    await callback.answer("Статус обновлён")


async def _get_branch(raw_id: str, session: AsyncSession, tenant_id: uuid.UUID) -> Branch | None:
    branch_id = parse_uuid(raw_id)
    if branch_id is None:
        return None
    return await BranchRepository(session, tenant_id).get(branch_id)
