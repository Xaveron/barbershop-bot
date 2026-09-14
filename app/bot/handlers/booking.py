"""Процесс записи: (Филиал) → Услуга → Барбер → Дата → Время → (Телефон) → Подтверждение."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.i18n import t
from app.bot.keyboards.callbacks import (
    BarberCB,
    BranchCB,
    ConfirmCB,
    DayCB,
    MenuCB,
    NavCB,
    ServiceCB,
    TimeCB,
)
from app.bot.keyboards.client import (
    back_to_main_kb,
    barbers_kb,
    branches_kb,
    confirm_kb,
    days_kb,
    main_menu_kb,
    phone_request_kb,
    remove_reply_kb,
    services_kb,
    times_kb,
)
from app.bot.states import BookingSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import Barber, Branch, Service, User
from app.database.repositories import (
    BarberRepository,
    BranchRepository,
    ServiceRepository,
    UserRepository,
)
from app.services.booking import BookingError, BookingService
from app.services.formatting import summary_block
from app.services.notifications import NotificationService
from app.services.schedule import ScheduleService
from app.utils.dt import combine_local, format_day, format_duration, hhmm_to_time
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_phone

logger = logging.getLogger(__name__)
router = Router(name="booking")


# --- Рендер шагов -----------------------------------------------------------
async def render_branch_or_skip(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    """Если у арендатора один активный филиал (или ни одного) — выбираем его
    молча, без клавиатуры: это сохраняет сегодняшний UX для всех, у кого пока
    один филиал. Показываем выбор только когда филиалов реально несколько."""
    branches = await BranchRepository(session, tenant_id).list_active()
    if len(branches) <= 1:
        if branches:
            await state.update_data(branch_id=str(branches[0].id))
        await render_services(callback, state, session, tenant_id, lang)
        return
    await state.set_state(BookingSG.branch)
    await edit_message(callback, t("booking.step_branch", lang), branches_kb(branches, lang))


async def render_services(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    services = await ServiceRepository(session, tenant_id).list_active()
    if not services:
        await edit_message(callback, t("booking.no_services", lang), back_to_main_kb(lang))
        return
    await state.set_state(BookingSG.service)
    await edit_message(callback, t("booking.step_service", lang), services_kb(services, lang))


async def render_barbers(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    branch_id: uuid.UUID,
    lang: str,
) -> None:
    barbers = await BarberRepository(session, tenant_id).list_active_for_branch(branch_id)
    if not barbers:
        await edit_message(callback, t("booking.no_barbers", lang), back_to_main_kb(lang))
        return
    await state.set_state(BookingSG.barber)
    await edit_message(callback, t("booking.step_barber", lang), barbers_kb(barbers, lang))


async def render_days(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    branch, service, barber = await _load_selection(state, session, tenant_id)
    if branch is None or service is None or barber is None:
        await _restart(callback, state, session, tenant_id, lang)
        return

    schedule = ScheduleService(session, settings, tenant_id, branch.id)
    days = await schedule.available_days(
        barber_id=barber.id, duration_minutes=service.duration_minutes
    )
    if not days:
        await edit_message(
            callback,
            t(
                "booking.no_days",
                lang,
                barber=esc(barber.name),
                days=settings.booking_horizon_days,
            ),
            barbers_kb(
                await BarberRepository(session, tenant_id).list_active_for_branch(branch.id), lang
            ),
        )
        await state.set_state(BookingSG.barber)
        return

    await state.set_state(BookingSG.day)
    header = f"{t('booking.step_day', lang)}\n\n💈 {esc(service.name)}\n👨‍💈 {esc(barber.name)}"
    await edit_message(callback, header, days_kb(days, lang, back_to="barber"))


async def render_times(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    data = await state.get_data()
    branch, service, barber = await _load_selection(state, session, tenant_id)
    day_raw = data.get("day")
    if branch is None or service is None or barber is None or not day_raw:
        await _restart(callback, state, session, tenant_id, lang)
        return

    day = date.fromisoformat(day_raw)
    schedule = ScheduleService(session, settings, tenant_id, branch.id)
    slots = await schedule.available_slots(
        barber_id=barber.id, day=day, duration_minutes=service.duration_minutes
    )
    if not slots:
        await alert(callback, t("booking.no_slots", lang))
        await render_days(callback, state, session, settings, tenant_id, lang)
        return

    await state.set_state(BookingSG.time)
    header = (
        f"{t('booking.step_time', lang)}\n\n"
        f"💈 {esc(service.name)}\n"
        f"👨‍💈 {esc(barber.name)}\n"
        f"📅 {format_day(day, lang)}\n"
        f"⏱ {format_duration(service.duration_minutes, lang)}"
    )
    await edit_message(callback, header, times_kb(slots, lang, back_to="day"))


def _summary_text(
    service: Service, barber: Barber, start_local: datetime, lang: str
) -> str:
    return summary_block(
        service_name=service.name,
        barber_name=barber.name,
        start_local=start_local,
        price=service.price,
        currency=service.currency,
        duration_minutes=service.duration_minutes,
        lang=lang,
    )


async def _show_summary_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    """Карточка подтверждения отдельным сообщением (после шага с телефоном)."""
    branch, service, barber = await _load_selection(state, session, tenant_id)
    data = await state.get_data()
    if (
        branch is None
        or service is None
        or barber is None
        or not data.get("day")
        or not data.get("time")
    ):
        await state.clear()
        await message.answer(t("booking.session_expired", lang), reply_markup=remove_reply_kb())
        return
    start_local = combine_local(
        date.fromisoformat(data["day"]), hhmm_to_time(data["time"]), settings.tz
    )
    await state.set_state(BookingSG.confirm)
    summary = _summary_text(service, barber, start_local, lang)
    await message.answer(
        f"{t('booking.check_details', lang)}\n\n{summary}", reply_markup=confirm_kb(lang)
    )


# --- Хендлеры ---------------------------------------------------------------
@router.callback_query(MenuCB.filter(F.action == "book"))
async def open_booking(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    await state.clear()
    await render_branch_or_skip(callback, state, session, tenant_id, lang)
    await callback.answer()


@router.callback_query(BookingSG.branch, BranchCB.filter())
async def choose_branch(
    callback: CallbackQuery,
    callback_data: BranchCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    branch_id = parse_uuid(callback_data.id)
    branch = (
        await BranchRepository(session, tenant_id).get_active(branch_id) if branch_id else None
    )
    if branch is None:
        await alert(callback, t("booking.branch_gone", lang))
        await render_branch_or_skip(callback, state, session, tenant_id, lang)
        return
    await state.update_data(branch_id=str(branch.id))
    await render_services(callback, state, session, tenant_id, lang)
    await callback.answer()


@router.callback_query(BookingSG.service, ServiceCB.filter())
async def choose_service(
    callback: CallbackQuery,
    callback_data: ServiceCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    service_id = parse_uuid(callback_data.id)
    service = (
        await ServiceRepository(session, tenant_id).get_active(service_id) if service_id else None
    )
    if service is None:
        await alert(callback, t("booking.service_gone", lang))
        await render_services(callback, state, session, tenant_id, lang)
        return
    data = await state.get_data()
    branch_id = parse_uuid(data.get("branch_id", ""))
    branch = (
        await BranchRepository(session, tenant_id).get_active(branch_id) if branch_id else None
    )
    if branch is None:
        await _restart(callback, state, session, tenant_id, lang)
        return
    await state.update_data(service_id=str(service.id))
    await render_barbers(callback, state, session, tenant_id, branch.id, lang)
    await callback.answer()


@router.callback_query(BookingSG.barber, BarberCB.filter())
async def choose_barber(
    callback: CallbackQuery,
    callback_data: BarberCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    barber_id = parse_uuid(callback_data.id)
    barber = (
        await BarberRepository(session, tenant_id).get_active(barber_id) if barber_id else None
    )
    if barber is None:
        data = await state.get_data()
        branch_id = parse_uuid(data.get("branch_id", ""))
        if branch_id is None:
            await _restart(callback, state, session, tenant_id, lang)
            return
        await alert(callback, t("booking.barber_gone", lang))
        await render_barbers(callback, state, session, tenant_id, branch_id, lang)
        return
    await state.update_data(barber_id=str(barber.id))
    await render_days(callback, state, session, settings, tenant_id, lang)
    await callback.answer()


@router.callback_query(BookingSG.day, DayCB.filter())
async def choose_day(
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
    await render_times(callback, state, session, settings, tenant_id, lang)
    await callback.answer()


@router.callback_query(BookingSG.time, TimeCB.filter())
async def choose_time(
    callback: CallbackQuery,
    callback_data: TimeCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    branch, service, barber = await _load_selection(state, session, tenant_id)
    data = await state.get_data()
    if branch is None or service is None or barber is None or not data.get("day"):
        await _restart(callback, state, session, tenant_id, lang)
        return
    try:
        chosen = hhmm_to_time(callback_data.value)
    except ValueError:
        await alert(callback, t("booking.bad_time", lang))
        return

    day = date.fromisoformat(data["day"])
    start_local = combine_local(day, chosen, settings.tz)

    schedule = ScheduleService(session, settings, tenant_id, branch.id)
    if not await schedule.is_slot_available(
        barber_id=barber.id, start=start_local, duration_minutes=service.duration_minutes
    ):
        await alert(callback, t("booking.slot_taken", lang))
        await render_times(callback, state, session, settings, tenant_id, lang)
        return

    await state.update_data(time=callback_data.value)

    # Необязательный шаг: телефон нужен барбершопу, чтобы позвонить клиенту.
    if settings.require_phone and not user.phone and callback.message is not None:
        await state.set_state(BookingSG.phone)
        await callback.message.answer(
            t("booking.ask_phone", lang), reply_markup=phone_request_kb(lang)
        )
        await callback.answer()
        return

    await state.set_state(BookingSG.confirm)
    summary = _summary_text(service, barber, start_local, lang)
    await edit_message(
        callback, f"{t('booking.check_details', lang)}\n\n{summary}", confirm_kb(lang)
    )
    await callback.answer()


@router.message(BookingSG.phone, F.contact)
async def receive_contact(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    if message.contact is not None:
        await UserRepository(session, tenant_id).set_phone(user, message.contact.phone_number[:32])
        await session.commit()
    await message.answer(t("booking.phone_saved", lang), reply_markup=remove_reply_kb())
    await _show_summary_message(message, state, session, settings, tenant_id, lang)


@router.message(BookingSG.phone)
async def receive_phone_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user: User,
    lang: str,
) -> None:
    raw = (message.text or "").strip()
    if raw == t("btn.skip", lang) or raw.lower() in {"skip", "пропустить", "omite"}:
        await message.answer(t("booking.phone_skipped", lang), reply_markup=remove_reply_kb())
        await _show_summary_message(message, state, session, settings, tenant_id, lang)
        return
    try:
        phone = validate_phone(raw)
    except ValidationError:
        await message.answer(t("booking.phone_invalid", lang), reply_markup=phone_request_kb(lang))
        return
    await UserRepository(session, tenant_id).set_phone(user, phone)
    await session.commit()
    await message.answer(t("booking.phone_saved", lang), reply_markup=remove_reply_kb())
    await _show_summary_message(message, state, session, settings, tenant_id, lang)


@router.callback_query(BookingSG.confirm, ConfirmCB.filter(F.action == "yes"))
async def confirm_booking(
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
    branch, service, barber = await _load_selection(state, session, tenant_id)
    if branch is None or service is None or barber is None or not data.get("day") or not data.get(
        "time"
    ):
        await _restart(callback, state, session, tenant_id, lang)
        return

    # Сразу сбрасываем состояние: повторное нажатие «Подтвердить»
    # не создаст вторую запись.
    await state.clear()

    start_local = combine_local(
        date.fromisoformat(data["day"]), hhmm_to_time(data["time"]), settings.tz
    )
    booking = BookingService(session, settings, tenant_id)
    try:
        appointment = await booking.create_appointment(
            user=user,
            branch_id=branch.id,
            barber_id=barber.id,
            service_id=service.id,
            start=start_local,
        )
    except BookingError as exc:
        await state.set_state(BookingSG.day)
        await state.update_data(
            branch_id=str(branch.id), service_id=str(service.id), barber_id=str(barber.id)
        )
        await alert(callback, t(exc.key, lang, **exc.params))
        await render_days(callback, state, session, settings, tenant_id, lang)
        return

    summary = _summary_text(service, barber, start_local, lang)
    await edit_message(
        callback,
        (
            f"{t('booking.confirmed_title', lang)}\n\n"
            f"{summary}\n\n"
            f"📍 {esc(settings.shop_address)}\n\n"
            f"{t('booking.reminder_note', lang)}"
        ),
        main_menu_kb(lang, is_admin=is_admin),
    )
    await callback.answer(t("booking.done", lang))

    notifier = NotificationService(bot, session_factory, settings, tenant_id)
    await notifier.notify_new_appointment(appointment)


@router.callback_query(BookingSG.confirm, ConfirmCB.filter(F.action == "no"))
async def decline_booking(
    callback: CallbackQuery, state: FSMContext, is_admin: bool, lang: str
) -> None:
    await state.clear()
    await edit_message(callback, t("booking.declined", lang), main_menu_kb(lang, is_admin=is_admin))
    await callback.answer()


# --- Навигация «назад» внутри процесса --------------------------------------
@router.callback_query(NavCB.filter(F.to == "service"))
async def nav_service(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    await render_services(callback, state, session, tenant_id, lang)
    await callback.answer()


@router.callback_query(NavCB.filter(F.to == "barber"))
async def nav_barber(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    data = await state.get_data()
    branch_id = parse_uuid(data.get("branch_id", ""))
    if branch_id is None:
        await _restart(callback, state, session, tenant_id, lang)
        return
    await render_barbers(callback, state, session, tenant_id, branch_id, lang)
    await callback.answer()


@router.callback_query(BookingSG.time, NavCB.filter(F.to == "day"))
async def nav_day(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    await render_days(callback, state, session, settings, tenant_id, lang)
    await callback.answer()


# --- Вспомогательное --------------------------------------------------------
async def _load_selection(
    state: FSMContext, session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[Branch | None, Service | None, Barber | None]:
    data = await state.get_data()
    branch_id = parse_uuid(data.get("branch_id", ""))
    service_id = parse_uuid(data.get("service_id", ""))
    barber_id = parse_uuid(data.get("barber_id", ""))
    branch = (
        await BranchRepository(session, tenant_id).get_active(branch_id) if branch_id else None
    )
    service = (
        await ServiceRepository(session, tenant_id).get_active(service_id) if service_id else None
    )
    barber = (
        await BarberRepository(session, tenant_id).get_active(barber_id) if barber_id else None
    )
    return branch, service, barber


async def _restart(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    await state.clear()
    await alert(callback, t("booking.session_expired", lang))
    await render_branch_or_skip(callback, state, session, tenant_id, lang)
