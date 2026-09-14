"""Мои записи: просмотр, отмена, перенос."""

from __future__ import annotations

import logging
import uuid
from datetime import date

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.i18n import t
from app.bot.keyboards.callbacks import ApptCB, ConfirmCB, DayCB, MenuCB, NavCB, TimeCB
from app.bot.keyboards.client import (
    appointment_actions_kb,
    back_to_main_kb,
    cancel_confirm_kb,
    confirm_kb,
    days_kb,
    main_menu_kb,
    my_appointments_kb,
    times_kb,
)
from app.bot.states import RescheduleSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import Appointment, CancelledBy, User
from app.services.booking import BookingError, BookingService
from app.services.formatting import appointment_card, summary_block
from app.services.notifications import NotificationService, client_language
from app.services.schedule import ScheduleService
from app.utils.dt import combine_local, format_day, hhmm_to_time
from app.utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="appointments")


async def render_my_appointments(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    booking = BookingService(session, settings, tenant_id)
    appointments = await booking.list_upcoming_for_user(user)
    if not appointments:
        await edit_message(
            callback,
            t("appointments.empty", lang),
            back_to_main_kb(lang),
        )
        return
    await edit_message(
        callback,
        t("appointments.title", lang, count=len(appointments)),
        my_appointments_kb(appointments, settings.tz, lang),
    )


@router.callback_query(MenuCB.filter(F.action == "my"))
@router.callback_query(NavCB.filter(F.to == "my"))
async def open_my_appointments(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    await state.clear()
    await render_my_appointments(callback, session, settings, tenant_id, user, lang)
    await callback.answer()


@router.callback_query(ApptCB.filter(F.action == "view"))
async def view_appointment(
    callback: CallbackQuery,
    callback_data: ApptCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    await state.clear()
    appointment = await _get_own(callback_data.id, session, settings, tenant_id, user)
    if appointment is None:
        await alert(callback, t("appointments.not_found", lang))
        await render_my_appointments(callback, session, settings, tenant_id, user, lang)
        return
    await edit_message(
        callback,
        appointment_card(appointment, settings.tz, with_status=True, lang=lang),
        appointment_actions_kb(str(appointment.id), lang),
    )
    await callback.answer()


@router.callback_query(ApptCB.filter(F.action == "cancel"))
async def ask_cancel(
    callback: CallbackQuery,
    callback_data: ApptCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    appointment = await _get_own(callback_data.id, session, settings, tenant_id, user)
    if appointment is None:
        await alert(callback, t("appointments.not_found", lang))
        return
    await edit_message(
        callback,
        t("appointments.cancel_question", lang)
        + "\n\n"
        + appointment_card(appointment, settings.tz, lang=lang),
        cancel_confirm_kb(str(appointment.id), lang),
    )
    await callback.answer()


@router.callback_query(ApptCB.filter(F.action == "cancel_ok"))
async def do_cancel(
    callback: CallbackQuery,
    callback_data: ApptCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    is_admin: bool,
    lang: str,
) -> None:
    appointment_id = parse_uuid(callback_data.id)
    if appointment_id is None:
        await alert(callback, t("appointments.invalid", lang))
        return

    booking = BookingService(session, settings, tenant_id)
    try:
        appointment = await booking.cancel_appointment(
            appointment_id=appointment_id,
            cancelled_by=CancelledBy.CLIENT,
            actor_user_id=user.id,
        )
    except BookingError as exc:
        await alert(callback, t(exc.key, lang, **exc.params))
        await render_my_appointments(callback, session, settings, tenant_id, user, lang)
        return

    await edit_message(
        callback,
        t("appointments.cancelled_title", lang)
        + "\n\n"
        + appointment_card(appointment, settings.tz, lang=lang),
        main_menu_kb(lang, is_admin=is_admin),
    )
    await callback.answer(t("appointments.cancelled_toast", lang))

    notifier = NotificationService(bot, session_factory, settings, tenant_id)
    await notifier.notify_cancelled(appointment, by_client=True)


# --- Перенос ----------------------------------------------------------------
@router.callback_query(ApptCB.filter(F.action == "move"))
async def start_reschedule(
    callback: CallbackQuery,
    callback_data: ApptCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    appointment = await _get_own(callback_data.id, session, settings, tenant_id, user)
    if appointment is None:
        await alert(callback, t("appointments.not_found", lang))
        return
    await state.clear()
    await state.update_data(appointment_id=str(appointment.id), by_admin=False)
    await state.set_state(RescheduleSG.day)
    await _render_reschedule_days(callback, state, session, settings, tenant_id, lang)
    await callback.answer()


async def _render_reschedule_days(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    appointment = await _appointment_from_state(state, session, settings, tenant_id)
    if appointment is None:
        await alert(callback, t("appointments.not_found", lang))
        await state.clear()
        return
    schedule = ScheduleService(session, settings, tenant_id)
    days = await schedule.available_days(
        barber_id=appointment.barber_id,
        duration_minutes=appointment.duration_minutes,
        exclude_appointment_id=appointment.id,
    )
    if not days:
        await edit_message(
            callback,
            t("appointments.no_days_to_move", lang),
            back_to_main_kb(lang),
        )
        await state.clear()
        return
    await state.set_state(RescheduleSG.day)
    await edit_message(
        callback,
        f"{t('appointments.move_title', lang)}\n"
        f"{appointment_card(appointment, settings.tz, lang=lang)}\n\n"
        f"{t('appointments.move_choose_day', lang)}",
        days_kb(days, lang, back_to="my"),
    )


@router.callback_query(RescheduleSG.day, DayCB.filter())
async def reschedule_pick_day(
    callback: CallbackQuery,
    callback_data: DayCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    try:
        day = date.fromisoformat(callback_data.value)
    except ValueError:
        await alert(callback, t("booking.bad_date", lang))
        return
    await state.update_data(day=day.isoformat())
    await _render_reschedule_times(callback, state, session, settings, tenant_id, lang)
    await callback.answer()


async def _render_reschedule_times(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    data = await state.get_data()
    appointment = await _appointment_from_state(state, session, settings, tenant_id)
    if appointment is None or not data.get("day"):
        await alert(callback, t("appointments.move_session_expired", lang))
        await state.clear()
        return
    day = date.fromisoformat(data["day"])
    schedule = ScheduleService(session, settings, tenant_id)
    slots = await schedule.available_slots(
        barber_id=appointment.barber_id,
        day=day,
        duration_minutes=appointment.duration_minutes,
        exclude_appointment_id=appointment.id,
    )
    if not slots:
        await alert(callback, t("appointments.no_slots_for_day", lang))
        await _render_reschedule_days(callback, state, session, settings, tenant_id, lang)
        return
    await state.set_state(RescheduleSG.time)
    await edit_message(
        callback,
        t("appointments.move_choose_time", lang, day=format_day(day, lang)),
        times_kb(slots, lang, back_to="day"),
    )


@router.callback_query(RescheduleSG.time, NavCB.filter(F.to == "day"))
async def reschedule_back_to_days(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    await _render_reschedule_days(callback, state, session, settings, tenant_id, lang)
    await callback.answer()


@router.callback_query(RescheduleSG.time, TimeCB.filter())
async def reschedule_pick_time(
    callback: CallbackQuery,
    callback_data: TimeCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    data = await state.get_data()
    appointment = await _appointment_from_state(state, session, settings, tenant_id)
    if appointment is None or not data.get("day"):
        await alert(callback, t("appointments.move_session_expired", lang))
        await state.clear()
        return
    try:
        chosen = hhmm_to_time(callback_data.value)
    except ValueError:
        await alert(callback, t("booking.bad_time", lang))
        return

    start_local = combine_local(date.fromisoformat(data["day"]), chosen, settings.tz)
    await state.update_data(time=callback_data.value)
    await state.set_state(RescheduleSG.confirm)
    summary = summary_block(
        service_name=appointment.service.name,
        barber_name=appointment.barber.name,
        start_local=start_local,
        price=appointment.price,
        currency=appointment.currency,
        duration_minutes=appointment.duration_minutes,
        lang=lang,
    )
    await edit_message(
        callback,
        f"{t('appointments.move_summary', lang)}\n\n{summary}",
        confirm_kb(lang),
    )
    await callback.answer()


@router.callback_query(RescheduleSG.confirm, ConfirmCB.filter(F.action == "yes"))
async def reschedule_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    is_admin: bool,
    lang: str,
) -> None:
    data = await state.get_data()
    appointment_id = parse_uuid(data.get("appointment_id", ""))
    day_raw, time_raw = data.get("day"), data.get("time")
    by_admin = bool(data.get("by_admin"))
    if appointment_id is None or not day_raw or not time_raw:
        await state.clear()
        await alert(callback, t("appointments.move_session_expired", lang))
        return

    await state.clear()
    start_local = combine_local(date.fromisoformat(day_raw), hhmm_to_time(time_raw), settings.tz)
    booking = BookingService(session, settings, tenant_id)
    try:
        appointment = await booking.reschedule_appointment(
            appointment_id=appointment_id,
            new_start=start_local,
            by_admin=by_admin,
            actor_user_id=None if by_admin else user.id,
        )
    except BookingError as exc:
        await alert(callback, t(exc.key, lang, **exc.params))
        await render_my_appointments(callback, session, settings, tenant_id, user, lang)
        return

    await edit_message(
        callback,
        t("appointments.moved_title", lang)
        + "\n\n"
        + appointment_card(appointment, settings.tz, lang=lang),
        main_menu_kb(lang, is_admin=is_admin),
    )
    await callback.answer(t("booking.done", lang))

    notifier = NotificationService(bot, session_factory, settings, tenant_id)
    if by_admin:
        client_lang = client_language(appointment, settings)
        await notifier.notify_client(
            appointment.user.telegram_id,
            t("appointments.moved_by_shop", client_lang)
            + "\n\n"
            + appointment_card(appointment, settings.tz, lang=client_lang)
            + "\n\n"
            + t("appointments.questions", client_lang, phone=esc(settings.shop_phone)),
        )
    else:
        admin_lang = settings.default_language
        await notifier.notify_admins(
            t("notify.client_moved", admin_lang)
            + "\n\n"
            + appointment_card(appointment, settings.tz, lang=admin_lang)
            + f"\n\n👤 {esc(appointment.user.display_name)}"
        )


@router.callback_query(RescheduleSG.confirm, ConfirmCB.filter(F.action == "no"))
async def reschedule_decline(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    await state.clear()
    await render_my_appointments(callback, session, settings, tenant_id, user, lang)
    await callback.answer(t("appointments.move_cancelled", lang))


# --- Вспомогательное --------------------------------------------------------
async def _get_own(
    raw_id: str,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
) -> Appointment | None:
    appointment_id = parse_uuid(raw_id)
    if appointment_id is None:
        return None
    appointment = await BookingService(session, settings, tenant_id).get_appointment(
        appointment_id
    )
    if appointment is None or appointment.user_id != user.id:
        return None
    return appointment


async def _appointment_from_state(
    state: FSMContext, session: AsyncSession, settings: Settings, tenant_id: uuid.UUID
) -> Appointment | None:
    data = await state.get_data()
    appointment_id = parse_uuid(data.get("appointment_id", ""))
    if appointment_id is None:
        return None
    return await BookingService(session, settings, tenant_id).get_appointment(appointment_id)
