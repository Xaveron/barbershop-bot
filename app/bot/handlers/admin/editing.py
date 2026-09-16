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
from app.bot.handlers.admin.branches import branch_card
from app.bot.handlers.admin.services import service_card
from app.bot.i18n import t
from app.bot.states import AdminFieldSG
from app.bot.utils import parse_uuid
from app.database.models import Permission, StaffMember
from app.database.repositories import BarberRepository, BranchRepository, ServiceRepository
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
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    data = await state.get_data()
    entity = data.get("entity")
    field = data.get("field")
    entity_id = parse_uuid(data.get("entity_id", ""))
    raw = message.text or ""

    if entity not in {"service", "barber", "branch"} or field is None or entity_id is None:
        await state.clear()
        await message.answer(t("admin.editing.session_expired", staff_lang))
        return

    # Защита на будущее: сегодня в это состояние можно попасть, только уже
    # пройдя MANAGE_SERVICES/MANAGE_STAFF/MANAGE_BRANCHES на роутере, который
    # его выставляет (services.py/barbers.py/branches.py) — эта проверка
    # ничего не меняет сейчас, но не даст будущему рефакторингу случайно
    # открыть сюда второй путь.
    permission = {
        "service": Permission.MANAGE_SERVICES,
        "barber": Permission.MANAGE_STAFF,
        "branch": Permission.MANAGE_BRANCHES,
    }[entity]
    try:
        AuthorizationService.require(staff, permission, is_super_admin=is_super_admin)
    except AuthorizationError:
        await state.clear()
        await message.answer(t("common.no_rights", staff_lang))
        return

    try:
        value = _parse_value(field, raw, staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return

    if entity == "service":
        service = await ServiceRepository(session, tenant_id).get(entity_id)
        if service is None:
            await state.clear()
            await message.answer(t("admin.service.not_found", staff_lang))
            return
        setattr(service, _COLUMNS[field], value)
        await state.clear()
        if not await _commit(session, message, staff_lang):
            return
        text, markup = service_card(service, staff_lang)
    elif entity == "barber":
        barber = await BarberRepository(session, tenant_id).get(entity_id)
        if barber is None:
            await state.clear()
            await message.answer(t("admin.barber.not_found", staff_lang))
            return
        setattr(barber, _COLUMNS[field], value)
        await state.clear()
        if not await _commit(session, message, staff_lang):
            return
        text, markup = await barber_card(barber, session, tenant_id, staff_lang)
    else:
        branch = await BranchRepository(session, tenant_id).get(entity_id)
        if branch is None:
            await state.clear()
            await message.answer(t("admin.branch.not_found", staff_lang))
            return
        setattr(branch, _COLUMNS[field], value)
        await state.clear()
        if not await _commit(session, message, staff_lang):
            return
        text, markup = branch_card(branch, staff_lang)

    await message.answer(t("admin.editing.saved", staff_lang) + text, reply_markup=markup)


_COLUMNS = {
    "name": "name",
    "duration": "duration_minutes",
    "price": "price",
    "description": "description",
    "address": "address",
}


def _parse_value(field: str, raw: str, lang: str) -> str | int | Decimal | None:
    if field == "name":
        return validate_name(raw, lang=lang)
    if field == "duration":
        return validate_duration(raw, lang=lang)
    if field == "price":
        return validate_price(raw, lang=lang)
    if field in ("description", "address"):
        return validate_description(raw, lang=lang)
    raise ValidationError(t("admin.editing.unknown_field", lang))


async def _commit(session: AsyncSession, message: Message, lang: str) -> bool:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось сохранить изменение")
        await message.answer(t("admin.editing.save_failed", lang))
        return False
    return True
