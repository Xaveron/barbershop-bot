"""Админ: рабочие часы и исключения из графика."""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_type
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import (
    back_to_admin_kb,
    barber_picker_kb,
    exceptions_kb,
    week_kb,
    weekday_actions_kb,
)
from app.bot.keyboards.callbacks import AdmCB, AdmDayCB
from app.bot.states import AdminExceptionSG, AdminScheduleSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.repositories import BarberRepository, ScheduleRepository
from app.services.schedule import ScheduleService
from app.utils.dt import WEEKDAYS_FULL, format_time, today_in
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_date, validate_time_range

logger = logging.getLogger(__name__)
router = Router(name="admin-schedule")

EXCEPTIONS_HORIZON_DAYS = 180


# --- Рабочие часы -----------------------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "schedule"))
async def pick_barber_for_schedule(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    barbers = await BarberRepository(session).list_all()
    if not barbers:
        await alert(callback, "Сначала добавьте барбера.")
        return
    await edit_message(
        callback,
        "🕐 <b>График работы</b>\n\nВыберите барбера:",
        barber_picker_kb(barbers, "sch_barber"),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "sch_barber"))
async def show_week(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await state.clear()
    barber_id = parse_uuid(callback_data.arg)
    barber = await BarberRepository(session).get(barber_id) if barber_id else None
    if barber is None:
        await alert(callback, "Барбер не найден.")
        return
    summary = await ScheduleService(session, settings).week_summary(barber.id)
    await edit_message(
        callback,
        f"🕐 <b>График: {esc(barber.name)}</b>\n\nВыберите день недели для изменения:",
        week_kb(str(barber.id), summary),
    )
    await callback.answer()


@router.callback_query(AdmDayCB.filter())
async def show_weekday(
    callback: CallbackQuery, callback_data: AdmDayCB, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    barber_id = parse_uuid(callback_data.barber)
    barber = await BarberRepository(session).get(barber_id) if barber_id else None
    if barber is None or not 0 <= callback_data.weekday <= 6:
        await alert(callback, "Барбер не найден.")
        return
    record = await ScheduleRepository(session).get_day(barber.id, callback_data.weekday)
    current = (
        f"{format_time(record.start_time)}-{format_time(record.end_time)}"
        if record
        else "выходной"
    )
    await edit_message(
        callback,
        f"🕐 <b>{esc(barber.name)} — {WEEKDAYS_FULL[callback_data.weekday]}</b>\n\n"
        f"Сейчас: {current}",
        weekday_actions_kb(str(barber.id), callback_data.weekday),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "sch_set"))
async def ask_hours(callback: CallbackQuery, callback_data: AdmCB, state: FSMContext) -> None:
    parsed = _parse_barber_weekday(callback_data.arg)
    if parsed is None:
        await alert(callback, "Некорректные данные.")
        return
    barber_id, weekday = parsed
    await state.set_state(AdminScheduleSG.hours)
    await state.update_data(barber_id=str(barber_id), weekday=weekday)
    await edit_message(
        callback,
        f"Отправьте рабочие часы на {WEEKDAYS_FULL[weekday]} в формате 10:00-19:00\n\n"
        "Для отмены: /cancel",
        back_to_admin_kb("sch_barber", str(barber_id)),
    )
    await callback.answer()


@router.message(AdminScheduleSG.hours)
async def save_hours(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    try:
        start, end = validate_time_range(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    data = await state.get_data()
    barber_id = parse_uuid(data.get("barber_id", ""))
    weekday = int(data.get("weekday", -1))
    if barber_id is None or not 0 <= weekday <= 6:
        await state.clear()
        await message.answer("Сессия устарела. Откройте /admin заново.")
        return

    await state.clear()
    try:
        await ScheduleRepository(session).set_day(barber_id, weekday, start, end)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось сохранить график")
        await message.answer("⚠️ Не удалось сохранить график.")
        return

    summary = await ScheduleService(session, settings).week_summary(barber_id)
    await message.answer(
        f"✅ {WEEKDAYS_FULL[weekday]}: {format_time(start)}-{format_time(end)}",
        reply_markup=week_kb(str(barber_id), summary),
    )


@router.callback_query(AdmCB.filter(F.action == "sch_off"))
async def set_day_off(
    callback: CallbackQuery, callback_data: AdmCB, session: AsyncSession, settings: Settings
) -> None:
    parsed = _parse_barber_weekday(callback_data.arg)
    if parsed is None:
        await alert(callback, "Некорректные данные.")
        return
    barber_id, weekday = parsed
    await ScheduleRepository(session).clear_day(barber_id, weekday)
    await session.commit()
    summary = await ScheduleService(session, settings).week_summary(barber_id)
    await edit_message(
        callback,
        f"✅ {WEEKDAYS_FULL[weekday]} теперь выходной.",
        week_kb(str(barber_id), summary),
    )
    await callback.answer("Сохранено")


# --- Исключения -------------------------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "exceptions"))
async def show_exceptions(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    await state.clear()
    today = today_in(settings.tz)
    exceptions = await ScheduleRepository(session).list_exceptions(
        date_from=today, date_to=today + timedelta(days=EXCEPTIONS_HORIZON_DAYS)
    )
    lines = ["🚫 <b>Исключения из графика</b>\n"]
    if not exceptions:
        lines.append("Пока нет запланированных исключений.")
    else:
        barbers = {barber.id: barber.name for barber in await BarberRepository(session).list_all()}
        for exception in exceptions:
            scope = "весь барбершоп" if exception.is_global else barbers.get(
                exception.barber_id, "барбер"
            )
            if exception.is_day_off:
                detail = "выходной"
            else:
                detail = (
                    f"{format_time(exception.start_time)}-{format_time(exception.end_time)}"
                    if exception.start_time and exception.end_time
                    else "особые часы"
                )
            lines.append(
                f"• {exception.exception_date.strftime('%d.%m.%Y')} — {esc(scope)}: {detail}"
            )
        lines.append("\nНажмите на исключение, чтобы удалить его.")
    await edit_message(callback, "\n".join(lines), exceptions_kb(exceptions))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "exc_add"))
async def add_exception_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    barbers = await BarberRepository(session).list_all()
    await edit_message(
        callback,
        "🚫 <b>Новое исключение</b>\n\nДля кого?",
        barber_picker_kb(barbers, "exc_who", back="exceptions", with_global=True),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "exc_who"))
async def add_exception_pick_date(
    callback: CallbackQuery, callback_data: AdmCB, state: FSMContext
) -> None:
    scope = callback_data.arg
    if scope != "all" and parse_uuid(scope) is None:
        await alert(callback, "Некорректный выбор.")
        return
    await state.set_state(AdminExceptionSG.date)
    await state.update_data(scope=scope)
    await edit_message(
        callback,
        "Отправьте дату в формате ДД.ММ.ГГГГ, например 31.12.2026\n\nДля отмены: /cancel",
        back_to_admin_kb("exceptions"),
    )
    await callback.answer()


@router.message(AdminExceptionSG.date)
async def add_exception_date(
    message: Message, state: FSMContext, settings: Settings
) -> None:
    try:
        exception_date = validate_date(
            message.text or "",
            not_before=today_in(settings.tz),
            max_days_ahead=EXCEPTIONS_HORIZON_DAYS,
        )
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(date=exception_date.isoformat())
    await state.set_state(AdminExceptionSG.mode)
    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 Выходной", callback_data=AdmCB(action="exc_mode", arg="off"))
    builder.button(text="🕐 Особые часы", callback_data=AdmCB(action="exc_mode", arg="hours"))
    builder.adjust(1)
    await message.answer(
        f"Дата: {exception_date.strftime('%d.%m.%Y')}\n\nЧто делаем?",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(AdminExceptionSG.mode, AdmCB.filter(F.action == "exc_mode"))
async def add_exception_mode(
    callback: CallbackQuery, callback_data: AdmCB, state: FSMContext, session: AsyncSession
) -> None:
    if callback_data.arg == "hours":
        await state.set_state(AdminExceptionSG.hours)
        await edit_message(
            callback,
            "Отправьте особые часы работы в формате 12:00-16:00\n\nДля отмены: /cancel",
            back_to_admin_kb("exceptions"),
        )
        await callback.answer()
        return

    saved = await _save_exception(state, session, is_day_off=True)
    if not saved:
        await alert(callback, "Не удалось сохранить исключение.")
        return
    await state.clear()
    await edit_message(callback, "✅ Исключение сохранено.", back_to_admin_kb("exceptions"))
    await callback.answer("Сохранено")


@router.message(AdminExceptionSG.hours)
async def add_exception_hours(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    try:
        start, end = validate_time_range(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    saved = await _save_exception(state, session, is_day_off=False, start=start, end=end)
    await state.clear()
    if not saved:
        await message.answer("⚠️ Не удалось сохранить исключение.")
        return
    await message.answer(
        f"✅ Исключение сохранено: {format_time(start)}-{format_time(end)}",
        reply_markup=back_to_admin_kb("exceptions"),
    )


@router.callback_query(AdmCB.filter(F.action == "exc_del"))
async def delete_exception(
    callback: CallbackQuery, callback_data: AdmCB, state: FSMContext, session: AsyncSession,
    settings: Settings
) -> None:
    exception_id = parse_uuid(callback_data.arg)
    repository = ScheduleRepository(session)
    exception = await repository.get_exception(exception_id) if exception_id else None
    if exception is None:
        await alert(callback, "Исключение не найдено.")
        return
    await repository.delete_exception(exception)
    await session.commit()
    await callback.answer("Удалено")
    await show_exceptions(callback, state, session, settings)


# --- Вспомогательное --------------------------------------------------------
def _parse_barber_weekday(raw: str) -> tuple[uuid.UUID, int] | None:
    parts = raw.split("|")
    if len(parts) != 2:
        return None
    barber_id = parse_uuid(parts[0])
    if barber_id is None or not parts[1].isdigit():
        return None
    weekday = int(parts[1])
    if not 0 <= weekday <= 6:
        return None
    return barber_id, weekday


async def _save_exception(
    state: FSMContext,
    session: AsyncSession,
    *,
    is_day_off: bool,
    start=None,
    end=None,
) -> bool:
    data = await state.get_data()
    scope = data.get("scope")
    raw_date = data.get("date")
    if not scope or not raw_date:
        return False
    barber_id = None if scope == "all" else parse_uuid(scope)
    if scope != "all" and barber_id is None:
        return False
    try:
        await ScheduleRepository(session).upsert_exception(
            barber_id=barber_id,
            exception_date=date_type.fromisoformat(raw_date),
            is_day_off=is_day_off,
            start_time=start,
            end_time=end,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось сохранить исключение")
        return False
    return True
