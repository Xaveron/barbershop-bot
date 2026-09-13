"""Информационные разделы: услуги, барберы, контакты, FAQ."""

from __future__ import annotations

import logging
from datetime import time

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import t
from app.bot.keyboards.callbacks import MenuCB
from app.bot.keyboards.client import back_to_main_kb
from app.bot.texts import contacts_text, faq_text
from app.bot.utils import edit_message
from app.config import Settings
from app.database.repositories import BarberRepository, ScheduleRepository, ServiceRepository
from app.utils.dt import format_duration, format_time, weekday_full
from app.utils.text import esc, money

logger = logging.getLogger(__name__)
router = Router(name="info")


@router.callback_query(MenuCB.filter(F.action == "services"))
async def show_services(callback: CallbackQuery, session: AsyncSession, lang: str) -> None:
    services = await ServiceRepository(session).list_active()
    if not services:
        await edit_message(callback, t("info.services_empty", lang), back_to_main_kb(lang))
        await callback.answer()
        return
    lines = [t("info.services_title", lang) + "\n"]
    for service in services:
        lines.append(
            f"<b>{esc(service.name)}</b>\n"
            f"💰 {money(service.price, service.currency)} · "
            f"⏱ {format_duration(service.duration_minutes, lang)}"
        )
        if service.description:
            lines.append(f"<i>{esc(service.description)}</i>")
        lines.append("")
    await edit_message(callback, "\n".join(lines).strip(), back_to_main_kb(lang))
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "barbers"))
async def show_barbers(callback: CallbackQuery, session: AsyncSession, lang: str) -> None:
    barbers = await BarberRepository(session).list_active()
    if not barbers:
        await edit_message(callback, t("info.barbers_empty", lang), back_to_main_kb(lang))
        await callback.answer()
        return
    lines = [t("info.barbers_title", lang) + "\n"]
    for barber in barbers:
        lines.append(f"<b>{esc(barber.name)}</b>")
        if barber.description:
            lines.append(f"<i>{esc(barber.description)}</i>")
        lines.append("")
    await edit_message(callback, "\n".join(lines).strip(), back_to_main_kb(lang))
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "contacts"))
async def show_contacts(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, lang: str
) -> None:
    schedule_lines = await _shop_schedule_lines(session, lang)
    await edit_message(
        callback,
        contacts_text(settings, schedule_lines, lang),
        back_to_main_kb(lang),
        disable_preview=False,
    )
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "faq"))
async def show_faq(callback: CallbackQuery, settings: Settings, lang: str) -> None:
    await edit_message(callback, faq_text(settings, lang), back_to_main_kb(lang))
    await callback.answer()


async def _shop_schedule_lines(session: AsyncSession, lang: str) -> list[str]:
    """График барбершопа = объединение графиков активных барберов."""
    barbers = await BarberRepository(session).list_active()
    schedules = ScheduleRepository(session)
    merged: dict[int, tuple[time, time]] = {}
    for barber in barbers:
        for record in await schedules.list_week(barber.id):
            current = merged.get(record.weekday)
            if current is None:
                merged[record.weekday] = (record.start_time, record.end_time)
            else:
                merged[record.weekday] = (
                    min(current[0], record.start_time),
                    max(current[1], record.end_time),
                )
    lines: list[str] = []
    for weekday in range(7):
        window = merged.get(weekday)
        title = weekday_full(weekday, lang)
        if window is None:
            lines.append(f"{title}: {t('info.day_off', lang)}")
        else:
            lines.append(f"{title}: {format_time(window[0])}–{format_time(window[1])}")
    return lines
