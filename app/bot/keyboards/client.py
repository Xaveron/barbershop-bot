"""Клавиатуры клиентской части (все подписи — через i18n)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.i18n import LANGUAGE_NAMES, t
from app.bot.keyboards.callbacks import (
    AdmCB,
    ApptCB,
    BarberCB,
    ConfirmCB,
    DayCB,
    LangCB,
    MenuCB,
    NavCB,
    ServiceCB,
    TimeCB,
)
from app.database.models import Appointment, Barber, Service
from app.utils.dt import format_day_with_weekday, format_time, time_to_hhmm, to_local
from app.utils.text import money


def main_menu_kb(lang: str, *, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn.book", lang), callback_data=MenuCB(action="book"))
    builder.button(text=t("btn.my", lang), callback_data=MenuCB(action="my"))
    builder.button(text=t("btn.services", lang), callback_data=MenuCB(action="services"))
    builder.button(text=t("btn.barbers", lang), callback_data=MenuCB(action="barbers"))
    builder.button(text=t("btn.contacts", lang), callback_data=MenuCB(action="contacts"))
    builder.button(text=t("btn.faq", lang), callback_data=MenuCB(action="faq"))
    builder.button(text=t("btn.language", lang), callback_data=MenuCB(action="language"))
    if is_admin:
        builder.button(text=t("btn.admin", lang), callback_data=AdmCB(action="menu"))
    builder.adjust(1, 1, 2, 2, 1, 1)
    return builder.as_markup()


def back_to_main_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn.back_to_menu", lang), callback_data=NavCB(to="main"))
    return builder.as_markup()


def languages_kb(lang: str, current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGE_NAMES.items():
        mark = "✅ " if code == current else ""
        builder.button(text=f"{mark}{name}", callback_data=LangCB(code=code))
    builder.button(text=t("btn.back_to_menu", lang), callback_data=NavCB(to="main"))
    builder.adjust(1)
    return builder.as_markup()


def services_kb(services: Sequence[Service], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in services:
        builder.button(
            text=f"{service.name} · {money(service.price, service.currency)}",
            callback_data=ServiceCB(id=str(service.id)),
        )
    builder.button(text=t("btn.back_to_menu", lang), callback_data=NavCB(to="main"))
    builder.adjust(1)
    return builder.as_markup()


def barbers_kb(barbers: Sequence[Barber], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for barber in barbers:
        builder.button(text=f"👨‍💈 {barber.name}", callback_data=BarberCB(id=str(barber.id)))
    builder.button(text=t("btn.back", lang), callback_data=NavCB(to="service"))
    builder.adjust(1)
    return builder.as_markup()


def days_kb(days: Sequence[date], lang: str, *, back_to: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day in days:
        builder.button(
            text=format_day_with_weekday(day, lang),
            callback_data=DayCB(value=day.isoformat()),
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text=t("btn.back", lang), callback_data=NavCB(to=back_to).pack())
    )
    return builder.as_markup()


def times_kb(slots: Sequence[datetime], lang: str, *, back_to: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=format_time(slot), callback_data=TimeCB(value=time_to_hhmm(slot)))
    builder.adjust(4)
    builder.row(
        InlineKeyboardButton(text=t("btn.back", lang), callback_data=NavCB(to=back_to).pack())
    )
    return builder.as_markup()


def confirm_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn.confirm", lang), callback_data=ConfirmCB(action="yes"))
    builder.button(text=t("btn.cancel", lang), callback_data=ConfirmCB(action="no"))
    builder.adjust(2)
    return builder.as_markup()


def my_appointments_kb(
    appointments: Sequence[Appointment], tz, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for appointment in appointments:
        local = to_local(appointment.starts_at, tz)
        builder.button(
            text=f"{local.strftime('%d.%m')} {format_time(local)} · {appointment.service.name}",
            callback_data=ApptCB(action="view", id=str(appointment.id)),
        )
    builder.button(text=t("btn.book", lang), callback_data=MenuCB(action="book"))
    builder.button(text=t("btn.back_to_menu", lang), callback_data=NavCB(to="main"))
    builder.adjust(1)
    return builder.as_markup()


def appointment_actions_kb(appointment_id: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("btn.reschedule", lang), callback_data=ApptCB(action="move", id=appointment_id)
    )
    builder.button(
        text=t("btn.cancel_appointment", lang),
        callback_data=ApptCB(action="cancel", id=appointment_id),
    )
    builder.button(text=t("btn.back_to_my", lang), callback_data=NavCB(to="my"))
    builder.adjust(2, 1)
    return builder.as_markup()


def cancel_confirm_kb(appointment_id: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("btn.cancel_yes", lang),
        callback_data=ApptCB(action="cancel_ok", id=appointment_id),
    )
    builder.button(
        text=t("btn.back", lang), callback_data=ApptCB(action="view", id=appointment_id)
    )
    builder.adjust(1)
    return builder.as_markup()


def phone_request_kb(lang: str) -> ReplyKeyboardMarkup:
    """Reply-клавиатура: Telegram сам подставит номер из профиля."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn.share_phone", lang), request_contact=True)],
            [KeyboardButton(text=t("btn.skip", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_reply_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
