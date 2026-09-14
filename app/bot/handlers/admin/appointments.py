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
from app.bot.states import RescheduleSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import AppointmentStatus, CancelledBy
from app.database.repositories import AppointmentRepository, NotificationRepository
from app.services.booking import BookingError, BookingService
from app.services.formatting import appointment_card
from app.services.notifications import NotificationService, client_language
from app.utils.dt import combine_local, format_day, now_utc, to_local
from app.utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="admin-appointments")

PAGE_SIZE = 8


@router.callback_query(AdmCB.filter(F.action == "appts"))
async def show_appointments(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    now = now_utc()
    horizon = now + timedelta(days=365)
    repository = AppointmentRepository(session, tenant_id)
    total = await repository.count_between(
        start=now, end=horizon, statuses=(AppointmentStatus.CONFIRMED,)
    )
    appointments = await repository.list_between(
        start=now,
        end=horizon,
        statuses=(AppointmentStatus.CONFIRMED,),
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
    await edit_message(
        callback, text, admin_appointments_kb(appointments, settings.tz, page, has_next)
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
    text = (
        appointment_card(appointment, settings.tz, with_status=True, lang=settings.default_language)
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
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    appointment_id = parse_uuid(callback_data.arg)
    if appointment_id is None:
        await alert(callback, "Некорректная запись.")
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
        + appointment_card(appointment, settings.tz, lang=settings.default_language),
        back_to_admin_kb("appts", "0"),
    )
    await callback.answer("Отменено")

    notifier = NotificationService(bot, session_factory, settings, tenant_id)
    lang = client_language(appointment, settings)
    await notifier.notify_client(
        appointment.user.telegram_id,
        t("appointments.cancelled_by_shop", lang)
        + "\n\n"
        + appointment_card(appointment, settings.tz, lang=lang)
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
) -> None:
    """Клиент не пришёл: запись закрывается, напоминания снимаются."""
    appointment_id = parse_uuid(callback_data.arg)
    if appointment_id is None:
        await alert(callback, "Некорректная запись.")
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
        + appointment_card(appointment, settings.tz, lang=settings.default_language),
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
) -> None:
    await state.clear()
    now = now_utc()
    appointments = await AppointmentRepository(session, tenant_id).list_between(
        start=now,
        end=now + timedelta(days=30),
        statuses=(AppointmentStatus.CONFIRMED,),
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
        by_day[to_local(appt.starts_at, settings.tz).date()] += 1

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
) -> None:
    try:
        selected_date = date.fromisoformat(callback_data.arg)
    except ValueError:
        await alert(callback, "Некорректная дата.")
        return

    day_start = combine_local(selected_date, datetime.min.time(), settings.tz)
    day_end = day_start + timedelta(days=1)
    count = await AppointmentRepository(session, tenant_id).count_between(
        start=day_start, end=day_end, statuses=(AppointmentStatus.CONFIRMED,)
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

    repository = AppointmentRepository(session, tenant_id)
    notifications_repo = NotificationRepository(session)
    appointments = await repository.list_between(
        start=day_start, end=day_end,
        statuses=(AppointmentStatus.CONFIRMED,),
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
            + appointment_card(appt, settings.tz, lang=lang)
            + "\n\n"
            + t("appointments.apologies", lang, phone=esc(settings.shop_phone)),
        )
