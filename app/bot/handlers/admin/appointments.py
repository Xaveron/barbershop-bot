"""Админ: просмотр, отмена и перенос записей."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.handlers.appointments import _render_reschedule_days
from app.bot.i18n import t
from app.bot.keyboards.admin import (
    admin_appointment_kb,
    admin_appointments_kb,
    back_to_admin_kb,
    branch_picker_kb,
    bulk_cancel_days_kb,
    confirm_bulk_cancel_kb,
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import RescheduleSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import AppointmentStatus, Branch, CancelledBy, Permission, StaffMember
from app.database.repositories import (
    AppointmentRepository,
    BranchRepository,
    NotificationRepository,
)
from app.services.authorization import resolve_accessible_branch_ids
from app.services.booking import BookingError, BookingService
from app.services.formatting import appointment_card
from app.services.notifications import NotificationService, client_language
from app.utils.dt import combine_local, format_day, now_utc, to_local
from app.utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="admin-appointments")
router.message.filter(RequirePermission(Permission.MANAGE_BOOKINGS))
router.callback_query.filter(RequirePermission(Permission.MANAGE_BOOKINGS))

PAGE_SIZE = 8


async def _accessible_branch_ids(
    session: AsyncSession, tenant_id: uuid.UUID, staff: StaffMember | None, is_super_admin: bool,
) -> frozenset[uuid.UUID] | None:
    return await resolve_accessible_branch_ids(
        session, tenant_id, staff, is_super_admin=is_super_admin
    )


@router.callback_query(AdmCB.filter(F.action == "appts"))
async def show_appointments(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    now = now_utc()
    horizon = now + timedelta(days=365)
    branch_ids = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    repository = AppointmentRepository(session, tenant_id)
    total = await repository.count_between(
        start=now, end=horizon, statuses=(AppointmentStatus.CONFIRMED,), branch_ids=branch_ids
    )
    appointments = await repository.list_between(
        start=now,
        end=horizon,
        statuses=(AppointmentStatus.CONFIRMED,),
        branch_ids=branch_ids,
        limit=PAGE_SIZE,
        offset=page * PAGE_SIZE,
    )
    if not appointments:
        await edit_message(
            callback,
            t("admin.appointments.empty", staff_lang),
            back_to_admin_kb(staff_lang, "menu"),
        )
        await callback.answer()
        return

    has_next = (page + 1) * PAGE_SIZE < total
    text = t("admin.appointments.list_title", staff_lang, total=total)
    await edit_message(
        callback, text, admin_appointments_kb(appointments, page, has_next, staff_lang)
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "appt"))
async def show_appointment(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    await state.clear()
    appointment_id = parse_uuid(callback_data.arg)
    appointment = (
        await AppointmentRepository(session, tenant_id).get(appointment_id)
        if appointment_id
        else None
    )
    if appointment is None:
        await alert(callback, t("admin.appointment.not_found", staff_lang))
        return
    branch_ids = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if branch_ids is not None and appointment.branch_id not in branch_ids:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    text = (
        appointment_card(
            appointment, appointment.branch.tz, with_status=True, lang=staff_lang
        )
        + f"\n\n👤 {esc(appointment.user.display_name)}"
        + f"\n🆔 <code>{appointment.id}</code>"
    )
    await edit_message(callback, text, admin_appointment_kb(str(appointment.id), staff_lang))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "appt_cancel"))
async def cancel_appointment(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    staff_lang: str,
    tenant_default_language: str,
) -> None:
    appointment_id = parse_uuid(callback_data.arg)
    if appointment_id is None:
        await alert(callback, t("admin.appointment.invalid", staff_lang))
        return
    target = await AppointmentRepository(session, tenant_id).get(appointment_id)
    if target is None:
        await alert(callback, t("admin.appointment.not_found", staff_lang))
        return
    branch_ids = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if branch_ids is not None and target.branch_id not in branch_ids:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    try:
        appointment = await BookingService(session, settings, tenant_id).cancel_appointment(
            appointment_id=appointment_id, cancelled_by=CancelledBy.ADMIN
        )
    except BookingError as exc:
        await alert(callback, t(exc.key, staff_lang, **exc.params))
        return

    await edit_message(
        callback,
        t("admin.appointment.cancelled_by_admin_title", staff_lang)
        + appointment_card(appointment, appointment.branch.tz, lang=staff_lang),
        back_to_admin_kb(staff_lang, "appts", "0"),
    )
    await callback.answer(t("admin.appointment.cancelled_toast", staff_lang))

    notifier = NotificationService(bot, session_factory, settings, tenant_id)
    lang = client_language(appointment, tenant_default_language)
    await notifier.notify_client(
        appointment.user.telegram_id,
        t("appointments.cancelled_by_shop", lang)
        + "\n\n"
        + appointment_card(appointment, appointment.branch.tz, lang=lang)
        + "\n\n"
        + t("appointments.apologies", lang, phone=esc(settings.shop_phone)),
    )


@router.callback_query(AdmCB.filter(F.action == "appt_noshow"))
async def mark_no_show(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    """Клиент не пришёл: запись закрывается, напоминания снимаются."""
    appointment_id = parse_uuid(callback_data.arg)
    if appointment_id is None:
        await alert(callback, t("admin.appointment.invalid", staff_lang))
        return
    target = await AppointmentRepository(session, tenant_id).get(appointment_id)
    if target is None:
        await alert(callback, t("admin.appointment.not_found", staff_lang))
        return
    branch_ids = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if branch_ids is not None and target.branch_id not in branch_ids:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    try:
        appointment = await BookingService(session, settings, tenant_id).mark_no_show(
            appointment_id=appointment_id
        )
    except BookingError as exc:
        await alert(callback, t(exc.key, staff_lang, **exc.params))
        return

    await edit_message(
        callback,
        t("admin.appointment.no_show_title", staff_lang)
        + appointment_card(appointment, appointment.branch.tz, lang=staff_lang),
        back_to_admin_kb(staff_lang, "appts", "0"),
    )
    await callback.answer(t("admin.appointment.no_show_toast", staff_lang))


@router.callback_query(AdmCB.filter(F.action == "appt_move"))
async def move_appointment(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    appointment_id = parse_uuid(callback_data.arg)
    appointment = (
        await AppointmentRepository(session, tenant_id).get(appointment_id)
        if appointment_id
        else None
    )
    if appointment is None:
        await alert(callback, t("admin.appointment.not_found", staff_lang))
        return
    branch_ids = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if branch_ids is not None and appointment.branch_id not in branch_ids:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    await state.clear()
    await state.update_data(appointment_id=str(appointment.id), by_admin=True)
    await state.set_state(RescheduleSG.day)
    await _render_reschedule_days(
        callback, state, session, settings, tenant_id, staff_lang
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Массовая отмена за день — всегда внутри ОДНОГО филиала (см. Phase 9A §H-4):
# группировка дней и фактическое окно отмены используют один и тот же
# branch.tz, а сам branch_id передаётся в каждом callback явно (не через FSM
# state), чтобы устаревшая кнопка подтверждения не могла «переехать» на
# другой филиал, который сотрудник успел выбрать после.
# ---------------------------------------------------------------------------

def _parse_branch_date_arg(raw: str) -> tuple[uuid.UUID | None, date | None]:
    parts = raw.split("|")
    if len(parts) != 2:
        return None, None
    branch_id = parse_uuid(parts[0])
    try:
        selected_date = date.fromisoformat(parts[1])
    except ValueError:
        return branch_id, None
    return branch_id, selected_date


async def _resolve_bulk_cancel_branch(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    branch_id: uuid.UUID | None,
) -> Branch | None:
    """Единая точка проверки для confirm/execute: филиал должен существовать,
    быть активным и входить в доступные сотруднику — никогда не доверяем
    тому, что было показано на экране раньше."""
    if branch_id is None:
        return None
    branch = await BranchRepository(session, tenant_id).get_active(branch_id)
    if branch is None:
        return None
    accessible = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if accessible is not None and branch_id not in accessible:
        return None
    return branch


async def _render_bulk_cancel_days(
    callback: CallbackQuery, session: AsyncSession, tenant_id: uuid.UUID, branch: Branch, lang: str
) -> None:
    now = now_utc()
    appointments = await AppointmentRepository(session, tenant_id).list_between(
        start=now,
        end=now + timedelta(days=30),
        statuses=(AppointmentStatus.CONFIRMED,),
        branch_ids=frozenset({branch.id}),
        limit=500,
    )
    if not appointments:
        await edit_message(
            callback,
            t("admin.bulk_cancel.no_appointments_in_branch", lang, branch=esc(branch.name)),
            back_to_admin_kb(lang, "bcx_days"),
        )
        return
    by_day: dict[date, int] = defaultdict(int)
    for appt in appointments:
        by_day[to_local(appt.starts_at, branch.tz).date()] += 1
    await edit_message(
        callback,
        t("admin.bulk_cancel.pick_date_prompt", lang),
        bulk_cancel_days_kb(str(branch.id), sorted(by_day.items()), lang),
    )


@router.callback_query(AdmCB.filter(F.action == "bcx_days"))
async def show_bulk_cancel_days(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    await state.clear()
    branch_ids = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    all_branches = await BranchRepository(session, tenant_id).list_active()
    candidates = (
        all_branches if branch_ids is None else [b for b in all_branches if b.id in branch_ids]
    )
    if not candidates:
        await edit_message(
            callback,
            t("admin.bulk_cancel.no_accessible_branches", staff_lang),
            back_to_admin_kb(staff_lang, "appts", "0"),
        )
        await callback.answer()
        return
    if len(candidates) == 1:
        await _render_bulk_cancel_days(callback, session, tenant_id, candidates[0], staff_lang)
        await callback.answer()
        return
    await edit_message(
        callback,
        t("admin.bulk_cancel.pick_branch_prompt", staff_lang),
        branch_picker_kb(candidates, "bcx_branch", staff_lang, back="appts"),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "bcx_branch"))
async def pick_bulk_cancel_branch(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    branch_id = parse_uuid(callback_data.arg)
    branch = await _resolve_bulk_cancel_branch(
        session, tenant_id, staff, is_super_admin, branch_id
    )
    if branch is None:
        await alert(callback, t("admin.errors.no_rights_or_branch_unavailable", staff_lang))
        return
    await _render_bulk_cancel_days(callback, session, tenant_id, branch, staff_lang)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "bcx_conf"))
async def confirm_bulk_cancel(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    branch_id, selected_date = _parse_branch_date_arg(callback_data.arg)
    if selected_date is None:
        await alert(callback, t("admin.bulk_cancel.invalid_date", staff_lang))
        return
    branch = await _resolve_bulk_cancel_branch(
        session, tenant_id, staff, is_super_admin, branch_id
    )
    if branch is None:
        await alert(callback, t("admin.errors.no_rights_or_branch_unavailable", staff_lang))
        return

    day_start = combine_local(selected_date, datetime.min.time(), branch.tz)
    day_end = day_start + timedelta(days=1)
    count = await AppointmentRepository(session, tenant_id).count_between(
        start=day_start, end=day_end, statuses=(AppointmentStatus.CONFIRMED,),
        branch_ids=frozenset({branch.id}),
    )
    if count == 0:
        await alert(callback, t("admin.bulk_cancel.no_active_appointments", staff_lang))
        return

    day_str = format_day(selected_date, staff_lang)
    await edit_message(
        callback,
        t(
            "admin.bulk_cancel.confirm_title",
            staff_lang,
            branch=esc(branch.name),
            date=day_str,
            count=count,
        ),
        confirm_bulk_cancel_kb(str(branch.id), selected_date.isoformat(), count, staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "bcx_ok"))
async def execute_bulk_cancel(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    staff_lang: str,
    tenant_default_language: str,
) -> None:
    branch_id, selected_date = _parse_branch_date_arg(callback_data.arg)
    if selected_date is None:
        await alert(callback, t("admin.bulk_cancel.invalid_date", staff_lang))
        return
    branch = await _resolve_bulk_cancel_branch(
        session, tenant_id, staff, is_super_admin, branch_id
    )
    if branch is None:
        await alert(callback, t("admin.errors.no_rights_or_branch_unavailable", staff_lang))
        return

    day_start = combine_local(selected_date, datetime.min.time(), branch.tz)
    day_end = day_start + timedelta(days=1)

    repository = AppointmentRepository(session, tenant_id)
    notifications_repo = NotificationRepository(session)
    appointments = await repository.list_between(
        start=day_start, end=day_end,
        statuses=(AppointmentStatus.CONFIRMED,),
        branch_ids=frozenset({branch.id}),
        limit=500,
    )
    if not appointments:
        await alert(callback, t("admin.bulk_cancel.no_active_appointments", staff_lang))
        return

    now = now_utc()
    for appt in appointments:
        appt.status = AppointmentStatus.CANCELLED
        appt.cancelled_at = now
        appt.cancelled_by = CancelledBy.ADMIN
        await notifications_repo.drop_pending(appt.id)

    await session.commit()

    count = len(appointments)
    day_str = format_day(selected_date, staff_lang)
    logger.info(
        "Массовая отмена: %s записей на %s (филиал %s)", count, selected_date, branch.id
    )

    await edit_message(
        callback,
        t(
            "admin.bulk_cancel.done_title",
            staff_lang,
            count=count,
            date=day_str,
            branch=esc(branch.name),
        ),
        back_to_admin_kb(staff_lang, "appts", "0"),
    )
    await callback.answer(t("admin.bulk_cancel.done_toast", staff_lang, count=count))

    notifier = NotificationService(bot, session_factory, settings, tenant_id)
    for appt in appointments:
        lang = client_language(appt, tenant_default_language)
        await notifier.notify_client(
            appt.user.telegram_id,
            t("appointments.cancelled_by_shop", lang)
            + "\n\n"
            + appointment_card(appt, appt.branch.tz, lang=lang)
            + "\n\n"
            + t("appointments.apologies", lang, phone=esc(settings.shop_phone)),
        )
