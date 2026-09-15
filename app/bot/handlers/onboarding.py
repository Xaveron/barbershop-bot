"""Мастер онбординга нового арендатора (Phase 5).

Роутер намеренно без общего permission-фильтра: путь "ADMIN_ID становится
TENANT_OWNER" должен сработать ДО того, как у арендатора вообще появится
StaffMember (см. docs/TENANT_ONBOARDING_DESIGN.md). Callback-хендлеры
(`continue`, `activate`) — единственные независимо достижимые точки входа
(callback_data можно отправить и без похода через /start), поэтому каждый
из них сам проверяет MANAGE_TENANT инлайн — тот же паттерн "слабый фильтр +
точечная проверка", что уже используют admin/reports.py::export_csv и
admin/staff.py::toggle_staff_branch. Текстовые шаги мастера — обычные
FSM-хендлеры по состоянию: до них нельзя добраться, не пройдя один из этих
проверенных входов, потому что именно они выставляют состояние.
"""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import t
from app.bot.keyboards.callbacks import OnbCB
from app.bot.keyboards.client import main_menu_kb
from app.bot.states import OnboardingSG
from app.bot.utils import alert, edit_message
from app.config import Settings
from app.database.models import Barber, Permission, StaffMember
from app.database.repositories import (
    BarberRepository,
    BranchRepository,
    ScheduleRepository,
    ServiceRepository,
    TenantRepository,
)
from app.services.authorization import AuthorizationError, AuthorizationService
from app.services.onboarding import TenantOnboardingService
from app.utils.text import esc
from app.utils.validators import (
    ValidationError,
    validate_currency,
    validate_duration,
    validate_name,
    validate_price,
    validate_time_range,
    validate_timezone,
)

logger = logging.getLogger(__name__)
router = Router(name="onboarding")


async def _send(
    target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    if isinstance(target, CallbackQuery):
        await edit_message(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


def _require_manage_tenant(staff: StaffMember | None, is_super_admin: bool) -> None:
    AuthorizationService.require(staff, Permission.MANAGE_TENANT, is_super_admin=is_super_admin)


def _continue_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("onboarding.btn_continue", lang), callback_data=OnbCB(action="continue"))
    return builder.as_markup()


def _activate_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("onboarding.btn_activate", lang), callback_data=OnbCB(action="activate"))
    return builder.as_markup()


# --- Точка входа --------------------------------------------------------
async def render_onboarding_entry(
    target: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    await state.clear()
    tenant = await TenantRepository(session).get(tenant_id)
    name = tenant.name if tenant is not None else ""
    text = f"{t('onboarding.welcome', lang)}\n\n📛 {esc(name)}"
    await _send(target, text, _continue_kb(lang))


@router.callback_query(OnbCB.filter(F.action == "continue"))
async def continue_onboarding(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    lang: str,
) -> None:
    try:
        _require_manage_tenant(staff, is_super_admin)
    except AuthorizationError:
        await callback.answer(t("common.no_rights", lang), show_alert=True)
        return
    await _render_next_step(callback, state, session, settings, tenant_id, lang)
    await callback.answer()


# --- Определение следующего незавершённого шага --------------------------
async def _render_next_step(
    target: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    """Пересчитывается из реальных данных при каждом вызове — тот же
    принцип, что TenantOnboardingService.validate_ready (design decision C
    в docs/TENANT_ONBOARDING_DESIGN.md): нет отдельного "текущего шага",
    который мог бы разойтись с БД, поэтому шаг всегда безопасно повторить
    или продолжить с него после перезапуска бота."""
    await state.clear()

    branches = await BranchRepository(session, tenant_id).list_active()
    if not branches:
        await state.set_state(OnboardingSG.branch_name)
        await _send(target, t("onboarding.step_branch_name", lang))
        return
    branch = branches[0]

    services = await ServiceRepository(session, tenant_id).list_active()
    if not services:
        await state.update_data(branch_id=str(branch.id))
        await state.set_state(OnboardingSG.service_name)
        await _send(target, t("onboarding.step_service_name", lang))
        return

    barber = await _find_bookable_barber(session, tenant_id, branch.id)
    if barber is None:
        await state.update_data(branch_id=str(branch.id))
        await state.set_state(OnboardingSG.barber_name)
        await _send(target, t("onboarding.step_barber_name", lang))
        return

    schedule = await ScheduleRepository(session, tenant_id).list_week(barber.id, branch.id)
    if not schedule:
        await state.update_data(branch_id=str(branch.id), barber_id=str(barber.id))
        await state.set_state(OnboardingSG.schedule_hours)
        await _send(target, t("onboarding.step_schedule_hours", lang))
        return

    await _render_review(target, session, tenant_id, lang)


async def _find_bookable_barber(
    session: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID
) -> Barber | None:
    barbers = await BarberRepository(session, tenant_id).list_active_for_branch(branch_id)
    return barbers[0] if barbers else None


# --- Шаг: филиал (название → часовой пояс → валюта) -----------------------
@router.message(OnboardingSG.branch_name)
async def set_branch_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    try:
        name = validate_name(message.text or "")
    except ValidationError:
        await message.answer(f"⚠️ {t('onboarding.invalid_name', lang)}")
        return
    await state.update_data(branch_name=name)
    await state.set_state(OnboardingSG.branch_timezone)
    tenant = await TenantRepository(session).get(tenant_id)
    default_timezone = tenant.timezone if tenant is not None else settings.timezone
    await message.answer(t("onboarding.step_branch_timezone", lang, default=default_timezone))


@router.message(OnboardingSG.branch_timezone)
async def set_branch_timezone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    raw = (message.text or "").strip()
    if raw == "-":
        tenant = await TenantRepository(session).get(tenant_id)
        timezone = tenant.timezone if tenant is not None else settings.timezone
    else:
        try:
            timezone = validate_timezone(raw)
        except ValidationError:
            await message.answer(f"⚠️ {t('onboarding.invalid_timezone', lang)}")
            return
    await state.update_data(branch_timezone=timezone)
    await state.set_state(OnboardingSG.branch_currency)
    tenant = await TenantRepository(session).get(tenant_id)
    default_currency = tenant.currency if tenant is not None else settings.default_currency
    await message.answer(t("onboarding.step_branch_currency", lang, default=default_currency))


@router.message(OnboardingSG.branch_currency)
async def set_branch_currency(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    raw = (message.text or "").strip()
    if raw == "-":
        tenant = await TenantRepository(session).get(tenant_id)
        currency = tenant.currency if tenant is not None else settings.default_currency
    else:
        try:
            currency = validate_currency(raw)
        except ValidationError:
            await message.answer(f"⚠️ {t('onboarding.invalid_currency', lang)}")
            return

    data = await state.get_data()
    branch = await BranchRepository(session, tenant_id).create(
        name=data["branch_name"], timezone=data.get("branch_timezone"), currency=currency
    )
    await session.commit()
    logger.info("Онбординг: создан первый филиал %s (арендатор %s)", branch.id, tenant_id)
    await _render_next_step(message, state, session, settings, tenant_id, lang)


# --- Шаг: услуга (название → длительность → цена) -------------------------
@router.message(OnboardingSG.service_name)
async def set_service_name(message: Message, state: FSMContext, lang: str) -> None:
    try:
        name = validate_name(message.text or "")
    except ValidationError:
        await message.answer(f"⚠️ {t('onboarding.invalid_name', lang)}")
        return
    await state.update_data(service_name=name)
    await state.set_state(OnboardingSG.service_duration)
    await message.answer(t("onboarding.step_service_duration", lang))


@router.message(OnboardingSG.service_duration)
async def set_service_duration(message: Message, state: FSMContext, lang: str) -> None:
    try:
        duration = validate_duration(message.text or "")
    except ValidationError:
        await message.answer(f"⚠️ {t('onboarding.invalid_duration', lang)}")
        return
    await state.update_data(service_duration=duration)
    await state.set_state(OnboardingSG.service_price)
    await message.answer(t("onboarding.step_service_price", lang))


@router.message(OnboardingSG.service_price)
async def set_service_price(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    try:
        price = validate_price(message.text or "")
    except ValidationError:
        await message.answer(f"⚠️ {t('onboarding.invalid_price', lang)}")
        return

    data = await state.get_data()
    branch_id = uuid.UUID(data["branch_id"])
    branch = await BranchRepository(session, tenant_id).get(branch_id)
    currency = branch.currency if branch is not None else settings.default_currency
    service = await ServiceRepository(session, tenant_id).create(
        name=data["service_name"],
        duration_minutes=data["service_duration"],
        price=price,
        currency=currency,
    )
    await session.commit()
    logger.info("Онбординг: создана первая услуга %s (арендатор %s)", service.id, tenant_id)
    await _render_next_step(message, state, session, settings, tenant_id, lang)


# --- Шаг: барбер ----------------------------------------------------------
@router.message(OnboardingSG.barber_name)
async def set_barber_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    try:
        name = validate_name(message.text or "")
    except ValidationError:
        await message.answer(f"⚠️ {t('onboarding.invalid_name', lang)}")
        return

    data = await state.get_data()
    branch_id = uuid.UUID(data["branch_id"])
    branch_repo = BranchRepository(session, tenant_id)
    barber = await BarberRepository(session, tenant_id).create(name=name)
    await branch_repo.assign_barber(barber_id=barber.id, branch_id=branch_id)
    await session.commit()
    logger.info("Онбординг: создан первый барбер %s (арендатор %s)", barber.id, tenant_id)
    await _render_next_step(message, state, session, settings, tenant_id, lang)


# --- Шаг: график -----------------------------------------------------------
@router.message(OnboardingSG.schedule_hours)
async def set_schedule_hours(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    try:
        start, end = validate_time_range(message.text or "")
    except ValidationError:
        await message.answer(f"⚠️ {t('onboarding.invalid_hours', lang)}")
        return

    data = await state.get_data()
    branch_id = uuid.UUID(data["branch_id"])
    barber_id = uuid.UUID(data["barber_id"])
    schedule_repo = ScheduleRepository(session, tenant_id)
    for weekday in range(7):
        await schedule_repo.set_day(barber_id, branch_id, weekday, start, end)
    await session.commit()
    logger.info(
        "Онбординг: задан график барбера %s в филиале %s (арендатор %s)",
        barber_id,
        branch_id,
        tenant_id,
    )
    await _render_next_step(message, state, session, settings, tenant_id, lang)


# --- Обзор и активация -------------------------------------------------------
async def _render_review(
    target: Message | CallbackQuery, session: AsyncSession, tenant_id: uuid.UUID, lang: str
) -> None:
    readiness = await TenantOnboardingService(session, tenant_id).validate_ready()
    lines = [t("onboarding.review_title", lang), ""]
    if readiness.is_ready:
        lines.append(t("onboarding.review_ready", lang))
        markup = _activate_kb(lang)
    else:
        lines.append(t("onboarding.review_not_ready", lang))
        lines.extend(t(key, lang) for key in readiness.missing)
        markup = _continue_kb(lang)
    await _send(target, "\n".join(lines), markup)


@router.callback_query(OnbCB.filter(F.action == "activate"))
async def activate_tenant(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_admin: bool,
    is_super_admin: bool,
    lang: str,
) -> None:
    try:
        _require_manage_tenant(staff, is_super_admin)
    except AuthorizationError:
        await callback.answer(t("common.no_rights", lang), show_alert=True)
        return

    actor_telegram_id = callback.from_user.id if callback.from_user else 0
    readiness = await TenantOnboardingService(session, tenant_id).activate(
        actor_telegram_id=actor_telegram_id
    )
    if not readiness.is_ready:
        # Кто-то успел изменить данные между показом обзора и нажатием
        # "Запустить" — сервер всегда перепроверяет сам, одного клика клиента
        # недостаточно (см. docs/TENANT_ONBOARDING_DESIGN.md §13).
        await alert(callback, t("onboarding.activation_blocked", lang))
        await _render_review(callback, session, tenant_id, lang)
        return

    await state.clear()
    await edit_message(
        callback, t("onboarding.activated", lang), main_menu_kb(lang, is_admin=is_admin)
    )
    await callback.answer()
