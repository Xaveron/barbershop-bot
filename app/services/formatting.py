"""Единое форматирование карточек записей (используется и ботом, и напоминаниями)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.bot.i18n import t
from app.database.models import Appointment, AppointmentStatus
from app.utils.dt import DEFAULT_LANG, format_day, format_duration, format_time, to_local
from app.utils.text import esc, money

STATUS_KEYS: dict[AppointmentStatus, str] = {
    AppointmentStatus.CONFIRMED: "status.confirmed",
    AppointmentStatus.CANCELLED: "status.cancelled",
    AppointmentStatus.COMPLETED: "status.completed",
    AppointmentStatus.NO_SHOW: "status.no_show",
}


def status_label(status: AppointmentStatus, lang: str = DEFAULT_LANG) -> str:
    return t(STATUS_KEYS[status], lang)


def summary_block(
    *,
    service_name: str,
    barber_name: str,
    start_local: datetime,
    price: Decimal,
    currency: str,
    duration_minutes: int,
    lang: str = DEFAULT_LANG,
) -> str:
    """Итоговая карточка перед подтверждением записи."""
    return (
        f"💈 {esc(service_name)}\n"
        f"👨‍💈 {esc(barber_name)}\n"
        f"📅 {format_day(start_local.date(), lang)}\n"
        f"🕐 {format_time(start_local)}\n"
        f"💰 {money(price, currency)}\n"
        f"⏱ {format_duration(duration_minutes, lang)}"
    )


def appointment_card(
    appointment: Appointment,
    tz: ZoneInfo,
    *,
    with_status: bool = False,
    lang: str = DEFAULT_LANG,
) -> str:
    local = to_local(appointment.starts_at, tz)
    card = summary_block(
        service_name=appointment.service.name,
        barber_name=appointment.barber.name,
        start_local=local,
        price=appointment.price,
        currency=appointment.currency,
        duration_minutes=appointment.duration_minutes,
        lang=lang,
    )
    if with_status:
        card += f"\n📌 {status_label(appointment.status, lang)}"
    return card


def appointment_line(appointment: Appointment, tz: ZoneInfo, lang: str = DEFAULT_LANG) -> str:
    """Однострочное описание для списков."""
    local = to_local(appointment.starts_at, tz)
    return (
        f"{format_day(local.date(), lang)} {format_time(local)} — "
        f"{esc(appointment.service.name)} / {esc(appointment.barber.name)}"
    )
