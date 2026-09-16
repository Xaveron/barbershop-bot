"""Админ: сотрудники — просмотр, добавление, смена роли, деактивация,
привязка к филиалам.

Роутер гейтится VIEW_STAFF (список/карточка доступны и MANAGER), а мутации
(добавление/смена роли/деактивация/привязка филиала) — отдельной инлайн-
проверкой MANAGE_STAFF в каждом хендлере, тем же паттерном, что
admin/reports.py::export_csv и admin/editing.py::apply_field_edit (см.
docs/RBAC_DESIGN.md §4). Защита единственного активного владельца — служебный
инвариант StaffService (см. Phase 9A §H-2), а не свойство этого UI: он
работает даже если callback подделан."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import t
from app.bot.keyboards.admin import (
    ASSIGNABLE_ROLES,
    admin_staff_card_kb,
    admin_staff_kb,
    back_to_admin_kb,
    confirm_add_staff_kb,
    confirm_role_change_kb,
    confirm_staff_deactivate_kb,
    role_label,
    staff_add_role_kb,
    staff_change_role_kb,
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import AdminStaffSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.database.models import Permission, Role, StaffMember
from app.database.repositories import BranchRepository, StaffRepository
from app.services.authorization import AuthorizationError, AuthorizationService
from app.services.billing import BillingError
from app.services.staff import StaffLifecycleError, StaffService
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_telegram_id

logger = logging.getLogger(__name__)
router = Router(name="admin-staff")
router.message.filter(RequirePermission(Permission.VIEW_STAFF))
router.callback_query.filter(RequirePermission(Permission.VIEW_STAFF))

PAGE_SIZE = 8


def _parse_assignable_role(raw: str) -> Role | None:
    """TENANT_OWNER никогда не проходит — владелец не назначается через этот
    UI (см. ASSIGNABLE_ROLES/Phase 9A §H-1)."""
    try:
        role = Role(raw)
    except ValueError:
        return None
    return role if role in ASSIGNABLE_ROLES else None


def _require_manage_staff(staff: StaffMember | None, is_super_admin: bool) -> None:
    AuthorizationService.require(staff, Permission.MANAGE_STAFF, is_super_admin=is_super_admin)


async def _render_staff_list(
    callback: CallbackQuery, session: AsyncSession, tenant_id: uuid.UUID, page: int, lang: str
) -> None:
    repository = StaffRepository(session, tenant_id)
    total = await repository.count_all()
    staff_list = await repository.list_all(limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    if not staff_list and page > 0:
        # Страница за пределами данных (сотрудников стало меньше между
        # запросами) — откатываемся на первую, а не показываем пустой экран.
        await _render_staff_list(callback, session, tenant_id, 0, lang)
        return
    if not staff_list:
        text = t("admin.staff.empty", lang)
    else:
        lines = [t("admin.staff.list_title", lang, total=total) + "\n"]
        for staff in staff_list:
            mark = "✅" if staff.is_active else "🚫"
            role = role_label(staff.role, lang)
            lines.append(f"{mark} {staff.telegram_id} · {role}")
        text = "\n".join(lines)
    has_next = (page + 1) * PAGE_SIZE < total
    await edit_message(callback, text, admin_staff_kb(staff_list, lang, page, has_next))


@router.callback_query(AdmCB.filter(F.action == "staff"))
async def show_staff(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    await _render_staff_list(callback, session, tenant_id, page, staff_lang)
    await callback.answer()


async def _render_staff_card(
    callback: CallbackQuery,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember,
    lang: str,
) -> None:
    role = role_label(staff.role, lang)
    status = (
        t("admin.branch.status_active", lang)
        if staff.is_active
        else t("admin.branch.status_hidden", lang)
    )
    text = (
        t("admin.staff.card_title", lang, telegram_id=staff.telegram_id)
        + "\n\n"
        + t("admin.staff.card_role", lang, role=esc(role))
        + "\n"
        + t("admin.staff.card_status", lang, status=status)
    )
    branches: list = []
    assigned_ids: set[uuid.UUID] = set()
    if staff.role in (Role.MANAGER, Role.RECEPTIONIST, Role.BARBER):
        branch_repo = BranchRepository(session, tenant_id)
        branches = await branch_repo.list_active()
        assigned = await branch_repo.list_branches_for_staff(staff.id)
        assigned_ids = {branch.id for branch in assigned}
        text += "\n\n" + t("admin.staff.branches_hint", lang)
    else:
        text += "\n\n" + t("admin.staff.all_branches_hint", lang)
    await edit_message(callback, text, admin_staff_card_kb(staff, branches, assigned_ids, lang))


@router.callback_query(AdmCB.filter(F.action == "stf"))
async def show_staff_card(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    staff_id = parse_uuid(callback_data.arg)
    staff = await StaffRepository(session, tenant_id).get(staff_id) if staff_id else None
    if staff is None:
        await alert(callback, t("admin.staff.not_found", staff_lang))
        return
    await state.update_data(staff_id=str(staff.id))
    await _render_staff_card(callback, session, tenant_id, staff, staff_lang)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "stf_branch"))
async def toggle_staff_branch(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        AuthorizationService.require(staff, Permission.MANAGE_STAFF, is_super_admin=is_super_admin)
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return

    data = await state.get_data()
    target_staff_id = parse_uuid(data.get("staff_id", ""))
    branch_id = parse_uuid(callback_data.arg)
    if target_staff_id is None or branch_id is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return

    target = await StaffRepository(session, tenant_id).get(target_staff_id)
    if target is None:
        await alert(callback, t("admin.staff.not_found", staff_lang))
        return

    branch_repo = BranchRepository(session, tenant_id)
    assigned = await branch_repo.list_branches_for_staff(target.id)
    assigned_ids = {branch.id for branch in assigned}

    if branch_id in assigned_ids:
        if len(assigned_ids) <= 1:
            await alert(callback, t("admin.staff.cannot_unassign_last_branch", staff_lang))
            return
        await branch_repo.unassign_staff(staff_member_id=target.id, branch_id=branch_id)
    else:
        link = await branch_repo.assign_staff(staff_member_id=target.id, branch_id=branch_id)
        if link is None:
            await alert(callback, t("admin.staff.assign_failed", staff_lang))
            return
    await session.commit()
    await _render_staff_card(callback, session, tenant_id, target, staff_lang)
    await callback.answer(t("admin.errors.saved", staff_lang))


# --- Добавление сотрудника ----------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "stf_add"))
async def start_add_staff(
    callback: CallbackQuery,
    state: FSMContext,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    await state.clear()
    await state.set_state(AdminStaffSG.telegram_id)
    await edit_message(
        callback,
        t("admin.staff.add_title", staff_lang),
        back_to_admin_kb(staff_lang, "staff"),
    )
    await callback.answer()


@router.message(AdminStaffSG.telegram_id)
async def add_staff_telegram_id(
    message: Message,
    state: FSMContext,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await state.clear()
        await message.answer(t("common.no_rights", staff_lang))
        return
    try:
        telegram_id = validate_telegram_id(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(new_staff_telegram_id=telegram_id)
    await message.answer(
        t("admin.staff.pick_role_prompt", staff_lang), reply_markup=staff_add_role_kb(staff_lang)
    )


@router.callback_query(AdmCB.filter(F.action == "stf_add_role"))
async def pick_add_staff_role(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await state.clear()
        await alert(callback, t("common.no_rights", staff_lang))
        return
    role = _parse_assignable_role(callback_data.arg)
    data = await state.get_data()
    telegram_id = data.get("new_staff_telegram_id")
    if role is None or telegram_id is None:
        await state.clear()
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return
    await state.update_data(new_staff_role=role.value)
    await edit_message(
        callback,
        t(
            "admin.staff.create_confirm",
            staff_lang,
            telegram_id=telegram_id,
            role=esc(role_label(role, staff_lang)),
        ),
        confirm_add_staff_kb(staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "stf_add_confirm"))
async def finish_add_staff(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await state.clear()
        await alert(callback, t("common.no_rights", staff_lang))
        return
    data = await state.get_data()
    telegram_id = data.get("new_staff_telegram_id")
    role = _parse_assignable_role(data.get("new_staff_role", ""))
    await state.clear()
    if telegram_id is None or role is None or callback.from_user is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return

    try:
        new_staff = await StaffService(session, tenant_id).create_staff(
            actor_telegram_id=callback.from_user.id, telegram_id=telegram_id, role=role
        )
    except IntegrityError:
        await session.rollback()
        await alert(callback, t("admin.staff.telegram_id_taken", staff_lang))
        return
    except BillingError:
        await session.rollback()
        await alert(callback, t("admin.staff.limit_reached", staff_lang))
        return
    if new_staff is None:
        await alert(callback, t("admin.staff.create_failed", staff_lang))
        return
    await _render_staff_card(callback, session, tenant_id, new_staff, staff_lang)
    await callback.answer(t("admin.staff.added_toast", staff_lang))


# --- Смена роли -----------------------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "stf_role_pick"))
async def start_change_role(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    target_id = parse_uuid(callback_data.arg)
    target = await StaffRepository(session, tenant_id).get(target_id) if target_id else None
    if target is None:
        await alert(callback, t("admin.staff.not_found", staff_lang))
        return
    await edit_message(
        callback,
        t("admin.staff.role_pick_title", staff_lang, telegram_id=target.telegram_id),
        staff_change_role_kb(str(target.id), staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "stf_role_set"))
async def confirm_change_role(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    target_id, role = _parse_staff_role_arg(callback_data.arg)
    target = await StaffRepository(session, tenant_id).get(target_id) if target_id else None
    if target is None or role is None:
        await alert(callback, t("admin.staff.role_or_target_invalid", staff_lang))
        return
    await edit_message(
        callback,
        t(
            "admin.staff.role_change_confirm",
            staff_lang,
            telegram_id=target.telegram_id,
            role=esc(role_label(role, staff_lang)),
        ),
        confirm_role_change_kb(str(target.id), role.value, staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "stf_role_confirm"))
async def apply_change_role(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    target_id, role = _parse_staff_role_arg(callback_data.arg)
    target = await StaffRepository(session, tenant_id).get(target_id) if target_id else None
    if target is None or role is None or callback.from_user is None:
        await alert(callback, t("admin.staff.role_or_target_invalid", staff_lang))
        return
    try:
        await StaffService(session, tenant_id).change_role(
            actor_telegram_id=callback.from_user.id, staff=target, new_role=role
        )
    except StaffLifecycleError:
        await session.rollback()
        await alert(callback, t("admin.staff.sole_owner_protected", staff_lang))
        return
    await _render_staff_card(callback, session, tenant_id, target, staff_lang)
    await callback.answer(t("admin.staff.role_changed_toast", staff_lang))


# --- Деактивация ------------------------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "stf_deact"))
async def confirm_deactivate_staff(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    target_id = parse_uuid(callback_data.arg)
    target = await StaffRepository(session, tenant_id).get(target_id) if target_id else None
    if target is None:
        await alert(callback, t("admin.staff.not_found", staff_lang))
        return
    if not target.is_active:
        await alert(callback, t("admin.staff.already_deactivated", staff_lang))
        return
    await edit_message(
        callback,
        t("admin.staff.deactivate_confirm_prompt", staff_lang, telegram_id=target.telegram_id),
        confirm_staff_deactivate_kb(str(target.id), staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "stf_deact_ok"))
async def apply_deactivate_staff(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        _require_manage_staff(staff, is_super_admin)
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    target_id = parse_uuid(callback_data.arg)
    target = await StaffRepository(session, tenant_id).get(target_id) if target_id else None
    if target is None:
        await alert(callback, t("admin.staff.not_found", staff_lang))
        return
    if not target.is_active:
        await alert(callback, t("admin.staff.already_deactivated", staff_lang))
        return
    if callback.from_user is None:
        await alert(callback, t("admin.staff.actor_unknown", staff_lang))
        return
    try:
        await StaffService(session, tenant_id).deactivate(
            actor_telegram_id=callback.from_user.id, staff=target
        )
    except StaffLifecycleError:
        await session.rollback()
        await alert(callback, t("admin.staff.sole_owner_protected", staff_lang))
        return
    await _render_staff_card(callback, session, tenant_id, target, staff_lang)
    await callback.answer(t("admin.staff.deactivated_toast", staff_lang))


def _parse_staff_role_arg(raw: str) -> tuple[uuid.UUID | None, Role | None]:
    parts = raw.split("|")
    if len(parts) != 2:
        return None, None
    return parse_uuid(parts[0]), _parse_assignable_role(parts[1])
