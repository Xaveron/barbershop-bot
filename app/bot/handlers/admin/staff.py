"""Админ: сотрудники — просмотр и привязка к филиалам.

Роутер гейтится VIEW_STAFF (список/карточка доступны и MANAGER), а
мутация (привязка/отвязка филиала) — отдельной инлайн-проверкой MANAGE_STAFF
внутри toggle_staff_branch, тем же паттерном, что admin/reports.py::export_csv
и admin/editing.py::apply_field_edit (см. docs/RBAC_DESIGN.md §4)."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import ROLE_LABELS, admin_staff_card_kb, admin_staff_kb
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.utils import alert, edit_message, parse_uuid
from app.database.models import Permission, Role, StaffMember
from app.database.repositories import BranchRepository, StaffRepository
from app.services.authorization import AuthorizationError, AuthorizationService
from app.utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="admin-staff")
router.message.filter(RequirePermission(Permission.VIEW_STAFF))
router.callback_query.filter(RequirePermission(Permission.VIEW_STAFF))


@router.callback_query(AdmCB.filter(F.action == "staff"))
async def show_staff(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    await state.clear()
    staff_list = await StaffRepository(session, tenant_id).list_all()
    if not staff_list:
        text = "🧑‍💼 Сотрудников пока нет."
    else:
        lines = ["🧑‍💼 <b>Сотрудники</b>\n"]
        for staff in staff_list:
            mark = "✅" if staff.is_active else "🚫"
            role = ROLE_LABELS.get(staff.role, staff.role.value)
            lines.append(f"{mark} {staff.telegram_id} · {role}")
        text = "\n".join(lines)
    await edit_message(callback, text, admin_staff_kb(staff_list))
    await callback.answer()


async def _render_staff_card(
    callback: CallbackQuery, session: AsyncSession, tenant_id: uuid.UUID, staff: StaffMember
) -> None:
    role = ROLE_LABELS.get(staff.role, staff.role.value)
    text = (
        f"🧑‍💼 <b>{staff.telegram_id}</b>\n\n"
        f"Роль: {esc(role)}\n"
        f"Статус: {'активен' if staff.is_active else 'скрыт'}"
    )
    branches: list = []
    assigned_ids: set[uuid.UUID] = set()
    if staff.role in (Role.MANAGER, Role.RECEPTIONIST, Role.BARBER):
        branch_repo = BranchRepository(session, tenant_id)
        branches = await branch_repo.list_active()
        assigned = await branch_repo.list_branches_for_staff(staff.id)
        assigned_ids = {branch.id for branch in assigned}
        text += "\n\nФилиалы (нажмите, чтобы привязать/отвязать):"
    else:
        text += "\n\nЭта роль имеет доступ ко всем филиалам арендатора."
    await edit_message(callback, text, admin_staff_card_kb(staff, branches, assigned_ids))


@router.callback_query(AdmCB.filter(F.action == "stf"))
async def show_staff_card(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    await state.clear()
    staff_id = parse_uuid(callback_data.arg)
    staff = await StaffRepository(session, tenant_id).get(staff_id) if staff_id else None
    if staff is None:
        await alert(callback, "Сотрудник не найден.")
        return
    await state.update_data(staff_id=str(staff.id))
    await _render_staff_card(callback, session, tenant_id, staff)
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
) -> None:
    try:
        AuthorizationService.require(staff, Permission.MANAGE_STAFF, is_super_admin=is_super_admin)
    except AuthorizationError:
        await alert(callback, "Недостаточно прав.")
        return

    data = await state.get_data()
    target_staff_id = parse_uuid(data.get("staff_id", ""))
    branch_id = parse_uuid(callback_data.arg)
    if target_staff_id is None or branch_id is None:
        await alert(callback, "Сессия устарела. Откройте /admin заново.")
        return

    target = await StaffRepository(session, tenant_id).get(target_staff_id)
    if target is None:
        await alert(callback, "Сотрудник не найден.")
        return

    branch_repo = BranchRepository(session, tenant_id)
    assigned = await branch_repo.list_branches_for_staff(target.id)
    assigned_ids = {branch.id for branch in assigned}

    if branch_id in assigned_ids:
        if len(assigned_ids) <= 1:
            await alert(
                callback,
                "Нельзя убрать последний филиал — у сотрудника не останется доступа. "
                "Сначала привяжите другой филиал.",
            )
            return
        await branch_repo.unassign_staff(staff_member_id=target.id, branch_id=branch_id)
    else:
        link = await branch_repo.assign_staff(staff_member_id=target.id, branch_id=branch_id)
        if link is None:
            await alert(callback, "Не удалось привязать филиал.")
            return
    await session.commit()
    await _render_staff_card(callback, session, tenant_id, target)
    await callback.answer("Сохранено")
