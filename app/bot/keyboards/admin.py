"""Клавиатуры админ-панели."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.callbacks import AdmCB, AdmDayCB, NavCB
from app.database.models import Appointment, Barber, ScheduleException, Service
from app.utils.dt import WEEKDAYS_FULL, format_time, to_local
from app.utils.text import money


def _back(action: str, arg: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text="⬅️ Назад", callback_data=AdmCB(action=action, arg=arg).pack())


def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💇 Услуги", callback_data=AdmCB(action="services"))
    builder.button(text="👨‍💈 Барберы", callback_data=AdmCB(action="barbers"))
    builder.button(text="🕐 График", callback_data=AdmCB(action="schedule"))
    builder.button(text="🚫 Исключения", callback_data=AdmCB(action="exceptions"))
    builder.button(text="📅 Записи", callback_data=AdmCB(action="appts", arg="0"))
    builder.button(text="👥 Клиенты", callback_data=AdmCB(action="clients", arg="0"))
    builder.button(text="📊 Статистика", callback_data=AdmCB(action="stats"))
    builder.button(text="📥 Экспорт CSV", callback_data=AdmCB(action="export"))
    builder.button(text="⬅️ В меню", callback_data=NavCB(to="main"))
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def admin_services_kb(services: Sequence[Service]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in services:
        mark = "" if service.is_active else "🚫 "
        builder.button(
            text=f"{mark}{service.name} · {money(service.price, service.currency)}",
            callback_data=AdmCB(action="svc", arg=str(service.id)),
        )
    builder.button(text="➕ Добавить услугу", callback_data=AdmCB(action="svc_add"))
    builder.button(text="⬅️ Назад", callback_data=AdmCB(action="menu"))
    builder.adjust(1)
    return builder.as_markup()


def admin_service_kb(service: Service) -> InlineKeyboardMarkup:
    sid = str(service.id)
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data=AdmCB(action="svc_name", arg=sid))
    builder.button(text="⏱ Длительность", callback_data=AdmCB(action="svc_dur", arg=sid))
    builder.button(text="💰 Цена", callback_data=AdmCB(action="svc_price", arg=sid))
    builder.button(text="📝 Описание", callback_data=AdmCB(action="svc_desc", arg=sid))
    builder.button(
        text="🚫 Скрыть" if service.is_active else "✅ Показать",
        callback_data=AdmCB(action="svc_toggle", arg=sid),
    )
    builder.button(text="🗑 Удалить", callback_data=AdmCB(action="svc_del", arg=sid))
    builder.button(text="⬅️ К услугам", callback_data=AdmCB(action="services"))
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def admin_barbers_kb(barbers: Sequence[Barber]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for barber in barbers:
        mark = "" if barber.is_active else "🚫 "
        builder.button(
            text=f"{mark}{barber.name}",
            callback_data=AdmCB(action="brb", arg=str(barber.id)),
        )
    builder.button(text="➕ Добавить барбера", callback_data=AdmCB(action="brb_add"))
    builder.button(text="⬅️ Назад", callback_data=AdmCB(action="menu"))
    builder.adjust(1)
    return builder.as_markup()


def admin_barber_kb(barber: Barber) -> InlineKeyboardMarkup:
    bid = str(barber.id)
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Имя", callback_data=AdmCB(action="brb_name", arg=bid))
    builder.button(text="📝 Описание", callback_data=AdmCB(action="brb_desc", arg=bid))
    builder.button(text="🕐 График", callback_data=AdmCB(action="sch_barber", arg=bid))
    builder.button(
        text="🚫 Скрыть" if barber.is_active else "✅ Показать",
        callback_data=AdmCB(action="brb_toggle", arg=bid),
    )
    builder.button(text="🗑 Удалить", callback_data=AdmCB(action="brb_del", arg=bid))
    builder.button(text="⬅️ К барберам", callback_data=AdmCB(action="barbers"))
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def confirm_delete_kb(action: str, arg: str, back_action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Да, удалить", callback_data=AdmCB(action=action, arg=arg))
    builder.button(text="⬅️ Отмена", callback_data=AdmCB(action=back_action, arg=arg))
    builder.adjust(1)
    return builder.as_markup()


def barber_picker_kb(barbers: Sequence[Barber], action: str, *, back: str = "menu",
                     with_global: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for barber in barbers:
        builder.button(text=barber.name, callback_data=AdmCB(action=action, arg=str(barber.id)))
    if with_global:
        builder.button(text="🏠 Весь барбершоп", callback_data=AdmCB(action=action, arg="all"))
    builder.button(text="⬅️ Назад", callback_data=AdmCB(action=back))
    builder.adjust(1)
    return builder.as_markup()


def week_kb(barber_id: str, summary: dict[int, object]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for weekday in range(7):
        window = summary.get(weekday)
        label = (
            f"{WEEKDAYS_FULL[weekday]}: выходной"
            if window is None
            else f"{WEEKDAYS_FULL[weekday]}: "
            f"{format_time(window.start)}-{format_time(window.end)}"  # type: ignore[attr-defined]
        )
        builder.button(text=label, callback_data=AdmDayCB(barber=barber_id, weekday=weekday))
    builder.button(text="⬅️ Назад", callback_data=AdmCB(action="schedule"))
    builder.adjust(1)
    return builder.as_markup()


def weekday_actions_kb(barber_id: str, weekday: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Задать часы",
        callback_data=AdmCB(action="sch_set", arg=f"{barber_id}|{weekday}"),
    )
    builder.button(
        text="🚫 Сделать выходным",
        callback_data=AdmCB(action="sch_off", arg=f"{barber_id}|{weekday}"),
    )
    builder.button(text="⬅️ Назад", callback_data=AdmCB(action="sch_barber", arg=barber_id))
    builder.adjust(1)
    return builder.as_markup()


def exceptions_kb(exceptions: Sequence[ScheduleException]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for exception in exceptions:
        scope = "🏠" if exception.is_global else "👨‍💈"
        kind = "выходной" if exception.is_day_off else "особые часы"
        builder.button(
            text=f"{scope} {exception.exception_date.strftime('%d.%m.%Y')} · {kind}",
            callback_data=AdmCB(action="exc_del", arg=str(exception.id)),
        )
    builder.button(text="➕ Добавить исключение", callback_data=AdmCB(action="exc_add"))
    builder.button(text="⬅️ Назад", callback_data=AdmCB(action="menu"))
    builder.adjust(1)
    return builder.as_markup()


def admin_appointments_kb(
    appointments: Sequence[Appointment], tz, page: int, has_next: bool
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for appointment in appointments:
        local = to_local(appointment.starts_at, tz)
        builder.button(
            text=(
                f"{local.strftime('%d.%m %H:%M')} · {appointment.service.name}"
                f" · {appointment.barber.name}"
            ),
            callback_data=AdmCB(action="appt", arg=str(appointment.id)),
        )
    builder.adjust(1)
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=AdmCB(action="appts", arg=str(page - 1)).pack()
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="➡️", callback_data=AdmCB(action="appts", arg=str(page + 1)).pack()
            )
        )
    if navigation:
        builder.row(*navigation)
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить за день",
            callback_data=AdmCB(action="bcx_days").pack(),
        )
    )
    builder.row(_back("menu"))
    return builder.as_markup()


def bulk_cancel_days_kb(days: list[tuple[date, int]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day, count in days:
        builder.button(
            text=f"{day.strftime('%d.%m.%Y')} — {count} зап.",
            callback_data=AdmCB(action="bcx_conf", arg=day.isoformat()),
        )
    builder.button(text="⬅️ К записям", callback_data=AdmCB(action="appts", arg="0"))
    builder.adjust(1)
    return builder.as_markup()


def confirm_bulk_cancel_kb(day_iso: str, count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"❌ Да, отменить {count} зап.",
        callback_data=AdmCB(action="bcx_ok", arg=day_iso),
    )
    builder.button(text="⬅️ Назад", callback_data=AdmCB(action="bcx_days"))
    builder.adjust(1)
    return builder.as_markup()


def admin_appointment_kb(appointment_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 Перенести", callback_data=AdmCB(action="appt_move", arg=appointment_id)
    )
    builder.button(
        text="❌ Отменить", callback_data=AdmCB(action="appt_cancel", arg=appointment_id)
    )
    builder.button(
        text="🚫 Не пришёл", callback_data=AdmCB(action="appt_noshow", arg=appointment_id)
    )
    builder.button(text="⬅️ К записям", callback_data=AdmCB(action="appts", arg="0"))
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def clients_kb(page: int, has_next: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=AdmCB(action="clients", arg=str(page - 1)).pack()
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="➡️", callback_data=AdmCB(action="clients", arg=str(page + 1)).pack()
            )
        )
    if navigation:
        builder.row(*navigation)
    builder.row(_back("menu"))
    return builder.as_markup()


def export_periods_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="За 7 дней", callback_data=AdmCB(action="export_do", arg="7"))
    builder.button(text="За 30 дней", callback_data=AdmCB(action="export_do", arg="30"))
    builder.button(text="За 90 дней", callback_data=AdmCB(action="export_do", arg="90"))
    builder.button(text="Все записи", callback_data=AdmCB(action="export_do", arg="all"))
    builder.button(text="⬅️ Назад", callback_data=AdmCB(action="menu"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def back_to_admin_kb(action: str = "menu", arg: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_back(action, arg))
    return builder.as_markup()
