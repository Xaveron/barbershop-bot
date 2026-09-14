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
    bulk_cancel_days_kb,
    confirm_bulk_cancel_kb,
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import RescheduleSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import AppointmentStatus, CancelledBy, Permission, StaffMember
from app.database.repositories import AppointmentRepository, NotificationRepository
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
    callback: CallbackQuery, session: AsyncSession, settings: Settings,
    tenant_id: uuid.UUID, staff: StaffMember | None,
) -> frozenset[uuid.UUID] | None:
    is_super_admin = bool(callback.from_user and settings.is_admin(callback.from_user.id))
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
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    now = now_utc()
    horizon = now + timedelta(days=365)
    branch_ids = await _accessible_branch_ids(callback, session, settings, tenant_id, staff)
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
            callback, "📅 Предстоящих записей нет.", back_to_admin_kb("menu")
        )
        await callback.answer()
        return

    has_next = (page + 1) * PAGE_SIZE < total
    text = f"📅 <b>Предстоящие записи</b> (всего {total})\n\nВыберите запись:"
    await edit_message(callback, text, admin_appointments_kb(appointments, page, has_next))
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
) -> None:
    await state.clear()
    appointment_id = parse_uuid(callback_data.arg)
    appointment = (
        await AppointmentRepository(session, tenant_id).get(appointment_id)
        if appointment_id
        else None
    )
    if appointment is None:
        await alert(callback, "Запись не найдена.")
        return
    branch_ids = await _accessible_branch_ids(callback, session, settings, tenant_id, staff)
    if branch_ids is not None and appointment.branch_id not in branch_ids:
        await alert(callback, "Недостаточно прав.")
        return
    text = (
        appointment_card(
            appointment, appointment.branch.tz, with_status=True, lang=settings.default_language
        )
        + f"\n\n👤 {esc(appointment.user.display_name)}"
        + f"\n🆔 <code>{appointment.id}</code>"
    )
    await edit_message(callback, text, admin_appointment_kb(str(appointment.id)))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "appt_cancel"))
async def cancel_appointment(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    appointment_id = parse_uuid(callback_data.arg)
    if appointment_id is None:
        await alert(callback, "Некорректная запись.")
        return
    target = await AppointmentRepository(session, tenant_id).get(appointment_id)
    if target is None:
        await alert(callback, "Запись не найдена.")
        return
    branch_ids = await _accessible_branch_ids(callback, session, settings, tenant_id, staff)
    if branch_ids is not None and target.branch_id not in branch_ids:
        await alert(callback, "Недостаточно прав.")
        return
    try:
        appointment = await BookingService(session, settings, tenant_id).cancel_appointment(
            appointment_id=appointment_id, cancelled_by=CancelledBy.ADMIN
        )
    except BookingError as exc:
        await alert(callback, t(exc.key, settings.default_language, **exc.params))
        return

    await edit_message(
        callback,
        "❌ <b>Запись отменена администратором</b>\n\n"
        + appointment_card(appointment, appointment.branch.tz, lang=settings.default_language),
        back_to_admin_kb("appts", "0"),
    )
    await callback.answer("Отменено")

    notifier = NotificationService(bot, session_factory, settings, tenant_id)
    lang = client_language(appointment, settings)
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
) -> None:
    """Клиент не пришёл: запись закрывается, напоминания снимаются."""
    appointment_id = parse_uuid(callback_data.arg)
    if appointment_id is None:
        await alert(callback, "Некорректная запись.")
        return
    target = await AppointmentRepository(session, tenant_id).get(appointment_id)
    if target is None:
        await alert(callback, "Запись не найдена.")
        return
    branch_ids = await _accessible_branch_ids(callback, session, settings, tenant_id, staff)
    if branch_ids is not None and target.branch_id not in branch_ids:
        await alert(callback, "Недостаточно прав.")
        return
    try:
        appointment = await BookingService(session, settings, tenant_id).mark_no_show(
            appointment_id=appointment_id
        )
    except BookingError as exc:
        await alert(callback, t(exc.key, settings.default_language, **exc.params))
        return

    await edit_message(
        callback,
        "🚫 <b>Отмечено: клиент не пришёл</b>\n\n"
        + appointment_card(appointment, appointment.branch.tz, lang=settings.default_language),
        back_to_admin_kb("appts", "0"),
    )
    await callback.answer("Отмечено")


@router.callback_query(AdmCB.filter(F.action == "appt_move"))
async def move_appointment(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
) -> None:
    appointment_id = parse_uuid(callback_data.arg)
    appointment = (
        await AppointmentRepository(session, tenant_id).get(appointment_id)
        if appointment_id
        else None
    )
    if appointment is None:
        await alert(callback, "Запись не найдена.")
        return
    branch_ids = await _accessible_branch_ids(callback, session, settings, tenant_id, staff)
    if branch_ids is not None and appointment.branch_id not in branch_ids:
        await alert(callback, "Недостаточно прав.")
        return
    await state.clear()
    await state.update_data(appointment_id=str(appointment.id), by_admin=True)
    await state.set_state(RescheduleSG.day)
    await _render_reschedule_days(
        callback, state, session, settings, tenant_id, settings.default_language
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Массовая отмена за день
# ---------------------------------------------------------------------------

@router.callback_query(AdmCB.filter(F.action == "bcx_days"))
async def show_bulk_cancel_days(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
) -> None:
    await state.clear()
    now = now_utc()
    branch_ids = await _accessible_branch_ids(callback, session, settings, tenant_id, staff)
    appointments = await AppointmentRepository(session, tenant_id).list_between(
        start=now,
        end=now + timedelta(days=30),
        statuses=(AppointmentStatus.CONFIRMED,),
        branch_ids=branch_ids,
        limit=500,
    )
    if not appointments:
        await edit_message(
            callback, "📅 Нет предстоящих записей для отмены.", back_to_admin_kb("appts", "0")
        )
        await callback.answer()
        return

    by_day: dict[date, int] = defaultdict(int)
    for appt in appointments:
        by_day[to_local(appt.starts_at, appt.branch.tz).date()] += 1

    await edit_message(
        callback,
        "❌ <b>Массовая отмена за день</b>\n\nВыберите дату:",
        bulk_cancel_days_kb(sorted(by_day.items())),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "bcx_conf"))
async def confirm_bulk_cancel(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
) -> None:
    try:
        selected_date = date.fromisoformat(callback_data.arg)
    except ValueError:
        await alert(callback, "Некорректная дата.")
        return

    # Массовая отмена за день не привязана к одному филиалу — границы дня
    # считаем в settings.tz (тот же выбор, что и раньше), фактическая
    # выборка/отмена ниже уже фильтруется по доступным сотруднику филиалам.
    day_start = combine_local(selected_date, datetime.min.time(), settings.tz)
    day_end = day_start + timedelta(days=1)
    branch_ids = await _accessible_branch_ids(callback, session, settings, tenant_id, staff)
    count = await AppointmentRepository(session, tenant_id).count_between(
        start=day_start, end=day_end, statuses=(AppointmentStatus.CONFIRMED,),
        branch_ids=branch_ids,
    )
    if count == 0:
        await alert(callback, "На этот день нет активных записей.")
        return

    day_str = format_day(selected_date, settings.default_language)
    await edit_message(
        callback,
        f"❌ <b>Подтвердите отмену</b>\n\n"
        f"Дата: <b>{day_str}</b>\n"
        f"Записей: <b>{count}</b>\n\n"
        f"Каждый клиент получит уведомление об отмене.",
        confirm_bulk_cancel_kb(callback_data.arg, count),
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
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        selected_date = date.fromisoformat(callback_data.arg)
    except ValueError:
        await alert(callback, "Некорректная дата.")
        return

    day_start = combine_local(selected_date, datetime.min.time(), settings.tz)
    day_end = day_start + timedelta(days=1)

    branch_ids = await _accessible_branch_ids(callback, session, settings, tenant_id, staff)
    repository = AppointmentRepository(session, tenant_id)
    notifications_repo = NotificationRepository(session)
    appointments = await repository.list_between(
        start=day_start, end=day_end,
        statuses=(AppointmentStatus.CONFIRMED,),
        branch_ids=branch_ids,
        limit=500,
    )
    if not appointments:
        await alert(callback, "На этот день нет активных записей.")
        return

    now = now_utc()
    for appt in appointments:
        appt.status = AppointmentStatus.CANCELLED
        appt.cancelled_at = now
        appt.cancelled_by = CancelledBy.ADMIN
        await notifications_repo.drop_pending(appt.id)

    await session.commit()

    count = len(appointments)
    day_str = format_day(selected_date, settings.default_language)
    logger.info("Массовая отмена: %s записей на %s", count, selected_date)

    await edit_message(
        callback,
        f"✅ <b>Отменено {count} записей на {day_str}</b>\n\nОтправляем уведомления клиентам...",
        back_to_admin_kb("appts", "0"),
    )
    await callback.answer(f"Отменено: {count}")

    notifier = NotificationService(bot, session_factory, settings, tenant_id)
    for appt in appointments:
        lang = client_language(appt, settings)
        await notifier.notify_client(
            appt.user.telegram_id,
            t("appointments.cancelled_by_shop", lang)
            + "\n\n"
            + appointment_card(appt, appt.branch.tz, lang=lang)
            + "\n\n"
            + t("appointments.apologies", lang, phone=esc(settings.shop_phone)),
        )
