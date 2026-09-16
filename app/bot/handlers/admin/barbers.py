"""Админ: управление барберами."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.billing_ui import describe_billing_error
from app.bot.i18n import t
from app.bot.keyboards.admin import (
    admin_barber_branches_kb,
    admin_barber_kb,
    admin_barbers_kb,
    back_to_admin_kb,
    confirm_delete_kb,
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import AdminBarberSG, AdminFieldSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.database.models import Barber, LimitKey, Permission
from app.database.repositories import BarberRepository, BranchRepository, ScheduleRepository
from app.services.billing import BillingError, LimitService
from app.services.provisioning import BarberProvisioningService
from app.utils.dt import format_time, weekday_short
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_description, validate_name

logger = logging.getLogger(__name__)
router = Router(name="admin-barbers")
router.message.filter(RequirePermission(Permission.MANAGE_STAFF))
router.callback_query.filter(RequirePermission(Permission.MANAGE_STAFF))

PAGE_SIZE = 8


async def barber_card(
    barber: Barber, session: AsyncSession, tenant_id: uuid.UUID, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    """Обнаруженный по ходу Phase 9B, не связанный с ней баг: list_week
    получил обязательный branch_id ещё при переходе на multi-branch (Phase
    3/4), а этот вызов остался со старой (tenant-only) сигнатурой — падал
    TypeError на КАЖДОЙ отрисовке карточки барбера; ни один тест не покрывал
    этот путь. Показываем график по первому филиалу барбера (с меткой
    филиала, если их больше одного) — тот же принцип, что и у остальных
    однофилиальных сокращений в этом файле."""
    branches = await BranchRepository(session, tenant_id).list_for_barber(barber.id)
    if not branches:
        days = t("admin.barber.schedule_not_set", lang)
    else:
        schedules = await ScheduleRepository(session, tenant_id).list_week(
            barber.id, branches[0].id
        )
        if not schedules:
            days = t("admin.barber.schedule_not_set", lang)
        else:
            days = ", ".join(
                f"{weekday_short(item.weekday, lang)} {format_time(item.start_time)}-"
                f"{format_time(item.end_time)}"
                for item in schedules
            )
            if len(branches) > 1:
                days = f"{days} ({esc(branches[0].name)})"
    status = (
        t("admin.branch.status_active", lang)
        if barber.is_active
        else t("admin.branch.status_hidden", lang)
    )
    text = t(
        "admin.barber.card",
        lang,
        name=esc(barber.name),
        description=esc(barber.description or "—"),
        status=status,
        days=esc(days),
    )
    return text, admin_barber_kb(barber, lang)


async def barbers_list(
    session: AsyncSession, tenant_id: uuid.UUID, lang: str, page: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    """Пагинированный admin-список (см. Phase 9C §M-6) — отдельно от
    BarberRepository.list_all(limit=None), которым продолжают пользоваться
    operational-пикеры в admin/schedule.py (выбор барбера для графика/
    исключения): им нужны ВСЕ барберы разом, а не одна страница."""
    repository = BarberRepository(session, tenant_id)
    total = await repository.count_all()
    barbers = await repository.list_all(limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    if not barbers and page > 0:
        return await barbers_list(session, tenant_id, lang, 0)
    if not barbers:
        return t("admin.barbers.empty", lang), admin_barbers_kb(barbers, lang, page, False)
    lines = [t("admin.barbers.list_title", lang, total=total) + "\n"]
    for barber in barbers:
        lines.append(f"{'✅' if barber.is_active else '🚫'} {esc(barber.name)}")
    has_next = (page + 1) * PAGE_SIZE < total
    return "\n".join(lines), admin_barbers_kb(barbers, lang, page, has_next)


@router.callback_query(AdmCB.filter(F.action == "barbers"))
async def show_barbers(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    text, markup = await barbers_list(session, tenant_id, staff_lang, page)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brb"))
async def show_barber(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return
    text, markup = await barber_card(barber, session, tenant_id, staff_lang)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brb_branches"))
async def show_barber_branches(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return
    await state.update_data(barber_id=str(barber.id))
    await _render_barber_branches(callback, session, tenant_id, barber, staff_lang)
    await callback.answer()


async def _render_barber_branches(
    callback: CallbackQuery,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    barber: Barber,
    lang: str,
) -> None:
    branch_repo = BranchRepository(session, tenant_id)
    branches = await branch_repo.list_active()
    assigned = await branch_repo.list_for_barber(barber.id)
    assigned_ids = {branch.id for branch in assigned}
    text = t("admin.barber.branches_prompt", lang, name=esc(barber.name))
    await edit_message(
        callback, text, admin_barber_branches_kb(barber, branches, assigned_ids, lang)
    )


@router.callback_query(AdmCB.filter(F.action == "brb_branch"))
async def toggle_barber_branch(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    data = await state.get_data()
    barber_id = parse_uuid(data.get("barber_id", ""))
    branch_id = parse_uuid(callback_data.arg)
    if barber_id is None or branch_id is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return
    barber = await _get_barber(str(barber_id), session, tenant_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return

    branch_repo = BranchRepository(session, tenant_id)
    assigned = await branch_repo.list_for_barber(barber.id)
    assigned_ids = {branch.id for branch in assigned}

    if branch_id in assigned_ids:
        if len(assigned_ids) <= 1:
            await alert(callback, t("admin.barber.cannot_unassign_last_branch", staff_lang))
            return
        await branch_repo.unassign_barber(barber_id=barber.id, branch_id=branch_id)
    else:
        link = await branch_repo.assign_barber(barber_id=barber.id, branch_id=branch_id)
        if link is None:
            await alert(callback, t("admin.barber.assign_failed", staff_lang))
            return
    await session.commit()
    await _render_barber_branches(callback, session, tenant_id, barber, staff_lang)
    await callback.answer(t("admin.errors.saved", staff_lang))


@router.callback_query(AdmCB.filter(F.action == "brb_add"))
async def add_barber_start(callback: CallbackQuery, state: FSMContext, staff_lang: str) -> None:
    await state.clear()
    await state.set_state(AdminBarberSG.name)
    await edit_message(
        callback,
        t("admin.barber.add_title", staff_lang),
        back_to_admin_kb(staff_lang, "barbers"),
    )
    await callback.answer()


@router.message(AdminBarberSG.name)
async def add_barber_name(message: Message, state: FSMContext, staff_lang: str) -> None:
    try:
        name = validate_name(
            message.text or "", lang=staff_lang, field=t("admin.barber.field_name", staff_lang)
        )
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(name=name)
    await state.set_state(AdminBarberSG.description)
    await message.answer(t("admin.barber.add_step2", staff_lang))


@router.message(AdminBarberSG.description)
async def add_barber_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    try:
        description = validate_description(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    data = await state.get_data()
    await state.clear()
    try:
        barber = await BarberProvisioningService(session, tenant_id).create_barber(
            name=data["name"], description=description
        )
        # Единственный активный филиал — привязываем автоматически, чтобы для
        # сегодняшних (пока однофилиальных) арендаторов ничего не поменялось.
        # Для арендатора с несколькими филиалами явную привязку барбера к
        # нужным филиалам делает будущая фаза — сейчас такого UI нет.
        branches = await BranchRepository(session, tenant_id).list_active()
        if len(branches) == 1:
            await BranchRepository(session, tenant_id).assign_barber(
                barber_id=barber.id, branch_id=branches[0].id
            )
        await session.commit()
    except BillingError as exc:
        await session.rollback()
        await message.answer(f"⚠️ {describe_billing_error(exc, staff_lang)}")
        return
    except Exception:
        await session.rollback()
        logger.exception("Не удалось создать барбера")
        await message.answer(t("admin.barber.create_failed", staff_lang))
        return
    text, markup = await barber_card(barber, session, tenant_id, staff_lang)
    await message.answer(t("admin.barber.created", staff_lang) + text, reply_markup=markup)


_FIELD_PROMPT_KEYS = {
    "brb_name": ("name", "admin.barber.prompt_name"),
    "brb_desc": ("description", "admin.barber.prompt_description"),
}


@router.callback_query(AdmCB.filter(F.action.in_(set(_FIELD_PROMPT_KEYS))))
async def edit_barber_field(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return
    field, prompt_key = _FIELD_PROMPT_KEYS[callback_data.action]
    await state.set_state(AdminFieldSG.value)
    await state.update_data(entity="barber", field=field, entity_id=str(barber.id))
    await edit_message(
        callback,
        t(
            "admin.common.edit_field_prompt",
            staff_lang,
            name=esc(barber.name),
            prompt=t(prompt_key, staff_lang),
            cancel_hint=t("admin.common.cancel_hint", staff_lang),
        ),
        back_to_admin_kb(staff_lang, "brb", str(barber.id)),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brb_toggle"))
async def toggle_barber(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return
    if not barber.is_active:
        # Реактивация — это на один активный ресурс больше, поэтому
        # проверяется тем же LimitService.assert_can_create, что и создание
        # нового барбера (см. Phase 9B §M-2): деактивированные барберы не
        # должны позволять обойти MAX_BARBERS циклом скрыть→создать→показать.
        try:
            await LimitService(session, tenant_id).assert_can_create(LimitKey.MAX_BARBERS)
        except BillingError as exc:
            await session.rollback()
            await alert(callback, describe_billing_error(exc, staff_lang))
            return
    barber.is_active = not barber.is_active
    await session.commit()
    text, markup = await barber_card(barber, session, tenant_id, staff_lang)
    await edit_message(callback, text, markup)
    await callback.answer(t("admin.common.status_updated", staff_lang))


@router.callback_query(AdmCB.filter(F.action == "brb_del"))
async def ask_delete_barber(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return
    await edit_message(
        callback,
        t("admin.barber.delete_confirm", staff_lang, name=esc(barber.name)),
        confirm_delete_kb("brb_del_ok", str(barber.id), "brb", staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brb_del_ok"))
async def delete_barber(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return
    repository = BarberRepository(session, tenant_id)
    if await repository.has_appointments(barber.id):
        await alert(callback, t("admin.barber.delete_blocked", staff_lang))
        return
    try:
        await repository.delete(barber)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось удалить барбера")
        await alert(callback, t("admin.barber.delete_failed", staff_lang))
        return
    text, markup = await barbers_list(session, tenant_id, staff_lang)
    await edit_message(callback, t("admin.barber.deleted", staff_lang) + text, markup)
    await callback.answer(t("admin.common.deleted_toast", staff_lang))


async def _get_barber(raw_id: str, session: AsyncSession, tenant_id: uuid.UUID) -> Barber | None:
    barber_id = parse_uuid(raw_id)
    if barber_id is None:
        return None
    return await BarberRepository(session, tenant_id).get(barber_id)
