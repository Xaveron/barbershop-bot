"""Админ: управление услугами."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.billing_ui import describe_billing_error
from app.bot.i18n import t
from app.bot.keyboards.admin import (
    admin_service_branches_kb,
    admin_service_kb,
    admin_services_kb,
    back_to_admin_kb,
    confirm_delete_kb,
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import AdminFieldSG, AdminServiceSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import LimitKey, Permission, Service
from app.database.repositories import BranchRepository, ServiceRepository
from app.services.billing import BillingError, LimitService
from app.services.provisioning import ServiceProvisioningService
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
router.message.filter(RequirePermission(Permission.MANAGE_SERVICES))
router.callback_query.filter(RequirePermission(Permission.MANAGE_SERVICES))

PAGE_SIZE = 8


def service_card(service: Service, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    status = (
        t("admin.service.status_active", lang)
        if service.is_active
        else t("admin.service.status_hidden", lang)
    )
    text = t(
        "admin.service.card",
        lang,
        name=esc(service.name),
        price=money(service.price, service.currency),
        duration=format_duration(service.duration_minutes, lang),
        description=esc(service.description or "—"),
        status=status,
    )
    return text, admin_service_kb(service, lang)


async def services_list(
    session: AsyncSession, tenant_id: uuid.UUID, lang: str, page: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    """Пагинированный admin-список (см. Phase 9C §M-6) — отдельно от
    ServiceRepository.list_active(), которым продолжают пользоваться
    operational-флоу бронирования: им нужны ВСЕ активные услуги разом."""
    repository = ServiceRepository(session, tenant_id)
    total = await repository.count_all()
    services = await repository.list_all(limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    if not services and page > 0:
        return await services_list(session, tenant_id, lang, 0)
    if not services:
        return t("admin.services.empty", lang), admin_services_kb(services, lang, page, False)
    lines = [t("admin.services.list_title", lang, total=total) + "\n"]
    for service in services:
        mark = "✅" if service.is_active else "🚫"
        lines.append(
            f"{mark} {esc(service.name)} — {money(service.price, service.currency)}, "
            f"{format_duration(service.duration_minutes, lang)}"
        )
    has_next = (page + 1) * PAGE_SIZE < total
    return "\n".join(lines), admin_services_kb(services, lang, page, has_next)


@router.callback_query(AdmCB.filter(F.action == "services"))
async def show_services(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    text, markup = await services_list(session, tenant_id, staff_lang, page)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "svc"))
async def show_service(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, t("admin.service.not_found", staff_lang))
        return
    text, markup = service_card(service, staff_lang)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "svc_branches"))
async def show_service_branches(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, t("admin.service.not_found", staff_lang))
        return
    await state.update_data(service_id=str(service.id))
    await _render_service_branches(callback, session, tenant_id, service, staff_lang)
    await callback.answer()


async def _render_service_branches(
    callback: CallbackQuery,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    service: Service,
    lang: str,
) -> None:
    branch_repo = BranchRepository(session, tenant_id)
    branches = await branch_repo.list_active()
    available_ids = {
        branch.id
        for branch in branches
        if await branch_repo.service_available_at_branch(
            service_id=service.id, branch_id=branch.id
        )
    }
    text = t("admin.service.branches_prompt", lang, name=esc(service.name))
    await edit_message(
        callback, text, admin_service_branches_kb(service, branches, available_ids, lang)
    )


@router.callback_query(AdmCB.filter(F.action == "svc_branch"))
async def toggle_service_branch(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    data = await state.get_data()
    service_id = parse_uuid(data.get("service_id", ""))
    branch_id = parse_uuid(callback_data.arg)
    if service_id is None or branch_id is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return
    service = await _get_service(str(service_id), session, tenant_id)
    if service is None:
        await alert(callback, t("admin.service.not_found", staff_lang))
        return

    branch_repo = BranchRepository(session, tenant_id)
    currently_available = await branch_repo.service_available_at_branch(
        service_id=service.id, branch_id=branch_id
    )
    link = await branch_repo.assign_service(
        service_id=service.id, branch_id=branch_id, is_active=not currently_available
    )
    if link is None:
        await alert(callback, t("admin.service.availability_failed", staff_lang))
        return
    await session.commit()
    await _render_service_branches(callback, session, tenant_id, service, staff_lang)
    await callback.answer(t("admin.errors.saved", staff_lang))


# --- Создание услуги --------------------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "svc_add"))
async def add_service_start(callback: CallbackQuery, state: FSMContext, staff_lang: str) -> None:
    await state.clear()
    await state.set_state(AdminServiceSG.name)
    await edit_message(
        callback,
        t("admin.service.add_title", staff_lang),
        back_to_admin_kb(staff_lang, "services"),
    )
    await callback.answer()


@router.message(AdminServiceSG.name)
async def add_service_name(message: Message, state: FSMContext, staff_lang: str) -> None:
    try:
        name = validate_name(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(name=name)
    await state.set_state(AdminServiceSG.duration)
    await message.answer(t("admin.service.add_step2", staff_lang))


@router.message(AdminServiceSG.duration)
async def add_service_duration(message: Message, state: FSMContext, staff_lang: str) -> None:
    try:
        duration = validate_duration(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(duration=duration)
    await state.set_state(AdminServiceSG.price)
    await message.answer(t("admin.service.add_step3", staff_lang))


@router.message(AdminServiceSG.price)
async def add_service_price(message: Message, state: FSMContext, staff_lang: str) -> None:
    try:
        price = validate_price(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(price=str(price))
    await state.set_state(AdminServiceSG.description)
    await message.answer(t("admin.service.add_step4", staff_lang))


@router.message(AdminServiceSG.description)
async def add_service_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    try:
        description = validate_description(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return

    data = await state.get_data()
    await state.clear()
    provisioning = ServiceProvisioningService(session, tenant_id)
    try:
        service = await provisioning.create_service(
            name=data["name"],
            duration_minutes=int(data["duration"]),
            price=Decimal(data["price"]),
            description=description,
            currency=settings.default_currency,
        )
        await session.commit()
    except BillingError as exc:
        await session.rollback()
        await message.answer(f"⚠️ {describe_billing_error(exc, staff_lang)}")
        return
    except Exception:
        await session.rollback()
        logger.exception("Не удалось создать услугу")
        await message.answer(t("admin.service.create_failed", staff_lang))
        return

    text, markup = service_card(service, staff_lang)
    await message.answer(t("admin.service.created", staff_lang) + text, reply_markup=markup)


# --- Редактирование ---------------------------------------------------------
_FIELD_PROMPT_KEYS = {
    "svc_name": ("name", "admin.service.prompt_name"),
    "svc_dur": ("duration", "admin.service.prompt_duration"),
    "svc_price": ("price", "admin.service.prompt_price"),
    "svc_desc": ("description", "admin.service.prompt_description"),
}


@router.callback_query(AdmCB.filter(F.action.in_(set(_FIELD_PROMPT_KEYS))))
async def edit_service_field(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, t("admin.service.not_found", staff_lang))
        return
    field, prompt_key = _FIELD_PROMPT_KEYS[callback_data.action]
    await state.set_state(AdminFieldSG.value)
    await state.update_data(entity="service", field=field, entity_id=str(service.id))
    await edit_message(
        callback,
        t(
            "admin.common.edit_field_prompt",
            staff_lang,
            name=esc(service.name),
            prompt=t(prompt_key, staff_lang),
            cancel_hint=t("admin.common.cancel_hint", staff_lang),
        ),
        back_to_admin_kb(staff_lang, "svc", str(service.id)),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "svc_toggle"))
async def toggle_service(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, t("admin.service.not_found", staff_lang))
        return
    if not service.is_active:
        # Реактивация — на один активный ресурс больше, проверяется тем же
        # LimitService.assert_can_create, что и создание новой услуги (см.
        # Phase 9B §M-2): нельзя обойти MAX_SERVICES циклом скрыть→создать→
        # показать.
        try:
            await LimitService(session, tenant_id).assert_can_create(LimitKey.MAX_SERVICES)
        except BillingError as exc:
            await session.rollback()
            await alert(callback, describe_billing_error(exc, staff_lang))
            return
    service.is_active = not service.is_active
    await session.commit()
    text, markup = service_card(service, staff_lang)
    await edit_message(callback, text, markup)
    await callback.answer(t("admin.common.status_updated", staff_lang))


@router.callback_query(AdmCB.filter(F.action == "svc_del"))
async def ask_delete_service(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, t("admin.service.not_found", staff_lang))
        return
    await edit_message(
        callback,
        t("admin.service.delete_confirm", staff_lang, name=esc(service.name)),
        confirm_delete_kb("svc_del_ok", str(service.id), "svc", staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "svc_del_ok"))
async def delete_service(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    service = await _get_service(callback_data.arg, session, tenant_id)
    if service is None:
        await alert(callback, t("admin.service.not_found", staff_lang))
        return
    repository = ServiceRepository(session, tenant_id)
    if await repository.has_appointments(service.id):
        await alert(callback, t("admin.service.delete_blocked", staff_lang))
        return
    try:
        await repository.delete(service)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось удалить услугу")
        await alert(callback, t("admin.service.delete_failed", staff_lang))
        return
    text, markup = await services_list(session, tenant_id, staff_lang)
    await edit_message(callback, t("admin.service.deleted", staff_lang) + text, markup)
    await callback.answer(t("admin.common.deleted_toast", staff_lang))


async def _get_service(
    raw_id: str, session: AsyncSession, tenant_id: uuid.UUID
) -> Service | None:
    service_id = parse_uuid(raw_id)
    if service_id is None:
        return None
    return await ServiceRepository(session, tenant_id).get(service_id)
