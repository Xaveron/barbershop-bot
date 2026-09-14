"""Админ: универсальное редактирование одного поля сущности."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.barbers import barber_card
from app.bot.handlers.admin.services import service_card
from app.bot.states import AdminFieldSG
from app.bot.utils import parse_uuid
from app.config import Settings
from app.database.models import Permission, StaffMember
from app.database.repositories import BarberRepository, ServiceRepository
from app.services.authorization import AuthorizationError, AuthorizationService
from app.utils.text import esc
from app.utils.validators import (
    ValidationError,
    validate_description,
    validate_duration,
    validate_name,
    validate_price,
)

logger = logging.getLogger(__name__)
router = Router(name="admin-editing")


@router.message(AdminFieldSG.value)
async def apply_field_edit(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    settings: Settings,
    staff: StaffMember | None,
) -> None:
    data = await state.get_data()
    entity = data.get("entity")
    field = data.get("field")
    entity_id = parse_uuid(data.get("entity_id", ""))
    raw = message.text or ""

    if entity not in {"service", "barber"} or field is None or entity_id is None:
        await state.clear()
        await message.answer("Сессия редактирования устарела. Откройте /admin заново.")
        return

    # Защита на будущее: сегодня в это состояние можно попасть, только уже
    # пройдя MANAGE_SERVICES/MANAGE_STAFF на роутере, который его выставляет
    # (services.py/barbers.py) — эта проверка ничего не меняет сейчас, но не
    # даст будущему рефакторингу случайно открыть сюда второй путь.
    permission = Permission.MANAGE_SERVICES if entity == "service" else Permission.MANAGE_STAFF
    is_super_admin = bool(message.from_user and settings.is_admin(message.from_user.id))
    try:
        AuthorizationService.require(staff, permission, is_super_admin=is_super_admin)
    except AuthorizationError:
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    try:
        value = _parse_value(field, raw)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return

    if entity == "service":
        service = await ServiceRepository(session, tenant_id).get(entity_id)
        if service is None:
            await state.clear()
            await message.answer("Услуга не найдена.")
            return
        setattr(service, _COLUMNS[field], value)
        await state.clear()
        if not await _commit(session, message):
            return
        text, markup = service_card(service)
    else:
        barber = await BarberRepository(session, tenant_id).get(entity_id)
        if barber is None:
            await state.clear()
            await message.answer("Барбер не найден.")
            return
        setattr(barber, _COLUMNS[field], value)
        await state.clear()
        if not await _commit(session, message):
            return
        text, markup = await barber_card(barber, session, tenant_id)

    await message.answer("✅ Сохранено\n\n" + text, reply_markup=markup)


_COLUMNS = {
    "name": "name",
    "duration": "duration_minutes",
    "price": "price",
    "description": "description",
}


def _parse_value(field: str, raw: str) -> str | int | Decimal | None:
    if field == "name":
        return validate_name(raw)
    if field == "duration":
        return validate_duration(raw)
    if field == "price":
        return validate_price(raw)
    if field == "description":
        return validate_description(raw)
    raise ValidationError("Неизвестное поле.")


async def _commit(session: AsyncSession, message: Message) -> bool:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось сохранить изменение")
        await message.answer("⚠️ Не удалось сохранить: возможно, значение конфликтует с другим.")
        return False
    return True
