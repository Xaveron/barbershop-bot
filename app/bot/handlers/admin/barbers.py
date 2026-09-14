"""Админ: управление барберами."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import (
    admin_barber_kb,
    admin_barbers_kb,
    back_to_admin_kb,
    confirm_delete_kb,
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import AdminBarberSG, AdminFieldSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.database.models import Barber, Permission
from app.database.repositories import BarberRepository, BranchRepository, ScheduleRepository
from app.utils.dt import WEEKDAYS_SHORT, format_time
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_description, validate_name

logger = logging.getLogger(__name__)
router = Router(name="admin-barbers")
router.message.filter(RequirePermission(Permission.MANAGE_STAFF))
router.callback_query.filter(RequirePermission(Permission.MANAGE_STAFF))


async def barber_card(
    barber: Barber, session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[str, InlineKeyboardMarkup]:
    schedules = await ScheduleRepository(session, tenant_id).list_week(barber.id)
    if schedules:
        days = ", ".join(
            f"{WEEKDAYS_SHORT[item.weekday]} {format_time(item.start_time)}-"
            f"{format_time(item.end_time)}"
            for item in schedules
        )
    else:
        days = "не задан"
    text = (
        f"👨‍💈 <b>{esc(barber.name)}</b>\n\n"
        f"📝 {esc(barber.description or '—')}\n"
        f"👁 Статус: {'активен' if barber.is_active else 'скрыт'}\n"
        f"🕐 График: {esc(days)}"
    )
    return text, admin_barber_kb(barber)


async def barbers_list(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[str, InlineKeyboardMarkup]:
    barbers = await BarberRepository(session, tenant_id).list_all()
    if not barbers:
        return "👨‍💈 Барберов пока нет. Добавьте первого.", admin_barbers_kb(barbers)
    lines = ["👨‍💈 <b>Барберы</b>\n"]
    for barber in barbers:
        lines.append(f"{'✅' if barber.is_active else '🚫'} {esc(barber.name)}")
    return "\n".join(lines), admin_barbers_kb(barbers)


@router.callback_query(AdmCB.filter(F.action == "barbers"))
async def show_barbers(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    await state.clear()
    text, markup = await barbers_list(session, tenant_id)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brb"))
async def show_barber(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    await state.clear()
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, "Барбер не найден.")
        return
    text, markup = await barber_card(barber, session, tenant_id)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brb_add"))
async def add_barber_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminBarberSG.name)
    await edit_message(
        callback,
        "➕ <b>Новый барбер</b>\n\nШаг 1/2. Отправьте имя барбера.\nДля отмены: /cancel",
        back_to_admin_kb("barbers"),
    )
    await callback.answer()


@router.message(AdminBarberSG.name)
async def add_barber_name(message: Message, state: FSMContext) -> None:
    try:
        name = validate_name(message.text or "", field="Имя")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(name=name)
    await state.set_state(AdminBarberSG.description)
    await message.answer("Шаг 2/2. Короткое описание (или «-», чтобы пропустить)")


@router.message(AdminBarberSG.description)
async def add_barber_description(
    message: Message, state: FSMContext, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    try:
        description = validate_description(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    data = await state.get_data()
    await state.clear()
    try:
        barber = await BarberRepository(session, tenant_id).create(
            name=data["name"], description=description
        )
        # Единственный активный филиал — привязываем автоматически, чтобы для
        # сегодняшних (пока однофилиальных) арендаторов ничего не поменялось.
        # Для арендатора с несколькими филиалами явную привязку барбера к
        # нужным филиалам делает будущая фаза — сейчас такого UI нет.
        branches = await BranchRepository(session, tenant_id).list_active()
        if len(branches) == 1:
            await BranchRepository(session, tenant_id).assign_barber(
                barber_id=barber.id, branch_id=branches[0].id
            )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось создать барбера")
        await message.answer("⚠️ Не удалось создать барбера.")
        return
    text, markup = await barber_card(barber, session, tenant_id)
    await message.answer(
        "✅ Барбер создан. Не забудьте задать график работы.\n\n" + text, reply_markup=markup
    )


_FIELD_PROMPTS = {
    "brb_name": ("name", "Отправьте новое имя барбера."),
    "brb_desc": ("description", "Отправьте новое описание (или «-», чтобы очистить)."),
}


@router.callback_query(AdmCB.filter(F.action.in_(set(_FIELD_PROMPTS))))
async def edit_barber_field(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, "Барбер не найден.")
        return
    field, prompt = _FIELD_PROMPTS[callback_data.action]
    await state.set_state(AdminFieldSG.value)
    await state.update_data(entity="barber", field=field, entity_id=str(barber.id))
    await edit_message(
        callback,
        f"✏️ {esc(barber.name)}\n\n{prompt}\n\nДля отмены: /cancel",
        back_to_admin_kb("brb", str(barber.id)),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brb_toggle"))
async def toggle_barber(
    callback: CallbackQuery, callback_data: AdmCB, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, "Барбер не найден.")
        return
    barber.is_active = not barber.is_active
    await session.commit()
    text, markup = await barber_card(barber, session, tenant_id)
    await edit_message(callback, text, markup)
    await callback.answer("Статус обновлён")


@router.callback_query(AdmCB.filter(F.action == "brb_del"))
async def ask_delete_barber(
    callback: CallbackQuery, callback_data: AdmCB, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, "Барбер не найден.")
        return
    await edit_message(
        callback,
        f"🗑 Удалить барбера «{esc(barber.name)}»?\n\n"
        "При наличии активных записей удаление блокируется — используйте «Скрыть».",
        confirm_delete_kb("brb_del_ok", str(barber.id), "brb"),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "brb_del_ok"))
async def delete_barber(
    callback: CallbackQuery, callback_data: AdmCB, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    barber = await _get_barber(callback_data.arg, session, tenant_id)
    if barber is None:
        await alert(callback, "Барбер не найден.")
        return
    repository = BarberRepository(session, tenant_id)
    if await repository.has_appointments(barber.id):
        await alert(callback, "У барбера есть активные записи — можно только скрыть его.")
        return
    try:
        await repository.delete(barber)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось удалить барбера")
        await alert(callback, "Не удалось удалить: барбер используется в истории записей.")
        return
    text, markup = await barbers_list(session, tenant_id)
    await edit_message(callback, "🗑 Барбер удалён\n\n" + text, markup)
    await callback.answer("Удалено")


async def _get_barber(raw_id: str, session: AsyncSession, tenant_id: uuid.UUID) -> Barber | None:
    barber_id = parse_uuid(raw_id)
    if barber_id is None:
        return None
    return await BarberRepository(session, tenant_id).get(barber_id)
