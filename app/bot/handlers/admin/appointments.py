"""Админ: просмотр, отмена и перенос записей."""

from __future__ import annotations

import logging
from datetime import timedelta

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
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.states import RescheduleSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import AppointmentStatus, CancelledBy
from app.database.repositories import AppointmentRepository
from app.services.booking import BookingError, BookingService
from app.services.formatting import appointment_card
from app.services.notifications import NotificationService, client_language
from app.utils.dt import now_utc
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
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    now = now_utc()
    horizon = now + timedelta(days=365)
    repository = AppointmentRepository(session)
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
) -> None:
    await state.clear()
    appointment_id = parse_uuid(callback_data.arg)
    appointment = (
        await AppointmentRepository(session).get(appointment_id) if appointment_id else None
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
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    appointment_id = parse_uuid(callback_data.arg)
    if appointment_id is None:
        await alert(callback, "Некорректная запись.")
        return
    try:
        appointment = await BookingService(session, settings).cancel_appointment(
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

    notifier = NotificationService(bot, session_factory, settings)
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
) -> None:
    """Клиент не пришёл: запись закрывается, напоминания снимаются."""
    appointment_id = parse_uuid(callback_data.arg)
    if appointment_id is None:
        await alert(callback, "Некорректная запись.")
        return
    try:
        appointment = await BookingService(session, settings).mark_no_show(
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
) -> None:
    appointment_id = parse_uuid(callback_data.arg)
    appointment = (
        await AppointmentRepository(session).get(appointment_id) if appointment_id else None
    )
    if appointment is None:
        await alert(callback, "Запись не найдена.")
        return
    await state.clear()
    await state.update_data(appointment_id=str(appointment.id), by_admin=True)
    await state.set_state(RescheduleSG.day)
    await _render_reschedule_days(callback, state, session, settings, settings.default_language)
    await callback.answer()
