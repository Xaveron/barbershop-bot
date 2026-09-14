"""Админ: управление услугами."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import (
    admin_service_kb,
    admin_services_kb,
    back_to_admin_kb,
    confirm_delete_kb,
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.states import AdminFieldSG, AdminServiceSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import Service
from app.database.repositories import ServiceRepository
from app.utils.dt import format_duration
from app.utils.text import esc, money
from app.utils.validators import (
    ValidationError,
    validate_description,
    validate_duration,
    validate_name,
    validate_price,
)

logger = logging.getLogger(__name__)
router = Router(name="admin-services")


def service_card(service: Service) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        f"💇 <b>{esc(service.name)}</b>\n\n"
        f"💰 Цена: {money(service.price, service.currency)}\n"
        f"⏱ Длительность: {format_duration(service.duration_minutes)}\n"
        f"📝 Описание: {esc(service.description or '—')}\n"
        f"👁 Статус: {'активна' if service.is_active else 'скрыта'}"
    )
    return text, admin_service_kb(service)


async def services_list(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[str, InlineKeyboardMarkup]:
    services = await ServiceRepository(session, tenant_id).list_all()
    if not services:
        return "💇 Услуг пока нет. Добавьте первую.", admin_services_kb(services)
    lines = ["💇 <b>Услуги</b>\n"]
    for service in services:
        mark = "✅" if service.is_active else "🚫"
        lines.append(
            f"{mark} {esc(service.name)} — {money(service.price, service.currency)}, "
            f"{format_duration(service.duration_minutes)}"
        )
    return "\n".join(lines), admin_services_kb(services)


@router.callback_query(AdmCB.filter(F.action == "services"))
async def show_services(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    await state.clear()
    text, markup = await services_list(session, tenant_id)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "svc"))
async def show_service(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    await state.clear()
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, "Услуга не найдена.")
        return
    text, markup = service_card(service)
    await edit_message(callback, text, markup)
    await callback.answer()


# --- Создание услуги --------------------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "svc_add"))
async def add_service_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminServiceSG.name)
    await edit_message(
        callback,
        "➕ <b>Новая услуга</b>\n\nШаг 1/4. Отправьте название услуги.\n"
        "Для отмены: /cancel",
        back_to_admin_kb("services"),
    )
    await callback.answer()


@router.message(AdminServiceSG.name)
async def add_service_name(message: Message, state: FSMContext) -> None:
    try:
        name = validate_name(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(name=name)
    await state.set_state(AdminServiceSG.duration)
    await message.answer("Шаг 2/4. Длительность в минутах (кратно 5), например: 45")


@router.message(AdminServiceSG.duration)
async def add_service_duration(message: Message, state: FSMContext) -> None:
    try:
        duration = validate_duration(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(duration=duration)
    await state.set_state(AdminServiceSG.price)
    await message.answer("Шаг 3/4. Цена, например: 250")


@router.message(AdminServiceSG.price)
async def add_service_price(message: Message, state: FSMContext) -> None:
    try:
        price = validate_price(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(price=str(price))
    await state.set_state(AdminServiceSG.description)
    await message.answer("Шаг 4/4. Описание (или «-», чтобы пропустить)")


@router.message(AdminServiceSG.description)
async def add_service_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
) -> None:
    try:
        description = validate_description(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return

    data = await state.get_data()
    await state.clear()
    repository = ServiceRepository(session, tenant_id)
    try:
        service = await repository.create(
            name=data["name"],
            duration_minutes=int(data["duration"]),
            price=Decimal(data["price"]),
            description=description,
            currency=settings.default_currency,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось создать услугу")
        await message.answer("⚠️ Не удалось создать услугу. Возможно, такое название уже есть.")
        return

    text, markup = service_card(service)
    await message.answer("✅ Услуга создана\n\n" + text, reply_markup=markup)


# --- Редактирование ---------------------------------------------------------
_FIELD_PROMPTS = {
    "svc_name": ("name", "Отправьте новое название услуги."),
    "svc_dur": ("duration", "Отправьте новую длительность в минутах (кратно 5)."),
    "svc_price": ("price", "Отправьте новую цену, например: 300"),
    "svc_desc": ("description", "Отправьте новое описание (или «-», чтобы очистить)."),
}


@router.callback_query(AdmCB.filter(F.action.in_(set(_FIELD_PROMPTS))))
async def edit_service_field(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, "Услуга не найдена.")
        return
    field, prompt = _FIELD_PROMPTS[callback_data.action]
    await state.set_state(AdminFieldSG.value)
    await state.update_data(entity="service", field=field, entity_id=str(service.id))
    await edit_message(
        callback,
        f"✏️ {esc(service.name)}\n\n{prompt}\n\nДля отмены: /cancel",
        back_to_admin_kb("svc", str(service.id)),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "svc_toggle"))
async def toggle_service(
    callback: CallbackQuery, callback_data: AdmCB, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, "Услуга не найдена.")
        return
    service.is_active = not service.is_active
    await session.commit()
    text, markup = service_card(service)
    await edit_message(callback, text, markup)
    await callback.answer("Статус обновлён")


@router.callback_query(AdmCB.filter(F.action == "svc_del"))
async def ask_delete_service(
    callback: CallbackQuery, callback_data: AdmCB, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, "Услуга не найдена.")
        return
    await edit_message(
        callback,
        f"🗑 Удалить услугу «{esc(service.name)}»?\n\n"
        "Если по услуге есть активные записи, удаление будет заблокировано — "
        "используйте «Скрыть».",
        confirm_delete_kb("svc_del_ok", str(service.id), "svc"),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "svc_del_ok"))
async def delete_service(
    callback: CallbackQuery, callback_data: AdmCB, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, "Услуга не найдена.")
        return
    repository = ServiceRepository(session, tenant_id)
    if await repository.has_appointments(service.id):
        await alert(callback, "По услуге есть активные записи — можно только скрыть её.")
        return
    try:
        await repository.delete(service)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось удалить услугу")
        await alert(callback, "Не удалось удалить: услуга используется в истории записей.")
        return
    text, markup = await services_list(session, tenant_id)
    await edit_message(callback, "🗑 Услуга удалена\n\n" + text, markup)
    await callback.answer("Удалено")


async def _get_service(
    raw_id: str, session: AsyncSession, tenant_id: uuid.UUID
) -> Service | None:
    service_id = parse_uuid(raw_id)
    if service_id is None:
        return None
    return await ServiceRepository(session, tenant_id).get(service_id)
