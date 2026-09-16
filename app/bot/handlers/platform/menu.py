"""Платформенная админка: меню, список арендаторов, карточка, создание,
активация/приостановка (Phase 8). Только через выделенный платформенный бот
(RequirePlatformOperator — см. app/bot/middlewares/permissions.py); обычный
бот арендатора никогда не доходит до этого роутера."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import t
from app.bot.keyboards.callbacks import PlatformCB
from app.bot.keyboards.platform import (
    platform_menu_kb,
    platform_tenant_detail_kb,
    platform_tenants_kb,
)
from app.bot.middlewares.permissions import RequirePlatformOperator
from app.bot.states import PlatformSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.services.tenant_management import (
    TenantLifecycleError,
    TenantManagementService,
    TenantOverview,
)
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_name

router = Router(name="platform-menu")
router.message.filter(RequirePlatformOperator())
router.callback_query.filter(RequirePlatformOperator())

PLATFORM_MENU_TEXT = "🛠 <b>Платформа</b>\n\nВыберите раздел:"
TENANTS_PAGE_SIZE = 8


@router.message(Command("platform"))
async def cmd_platform(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(PLATFORM_MENU_TEXT, reply_markup=platform_menu_kb())


@router.callback_query(PlatformCB.filter(F.action == "menu"))
async def open_platform_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_message(callback, PLATFORM_MENU_TEXT, platform_menu_kb())
    await callback.answer()


def _tenant_card_text(overview: TenantOverview) -> str:
    lines = [
        f"🏢 <b>{esc(overview.name)}</b>",
        f"Слаг: <code>{esc(overview.slug)}</code>",
        f"Статус: <b>{overview.status.value}</b>",
        f"Часовой пояс: {esc(overview.timezone)} · Валюта: {esc(overview.currency)}",
        "",
        f"Филиалов: {overview.branch_count}",
        f"Сотрудников: {overview.staff_count}",
        f"Ботов: {overview.bot_count}",
        f"Тариф: {esc(overview.plan_code or '—')}",
        f"Подписка: {overview.subscription_status.value if overview.subscription_status else '—'}",
    ]
    return "\n".join(lines)


@router.callback_query(PlatformCB.filter(F.action == "tenants"))
async def show_tenants(
    callback: CallbackQuery, callback_data: PlatformCB, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    service = TenantManagementService(session)
    total = await service.count_tenants()
    overviews = await service.list_tenants(limit=TENANTS_PAGE_SIZE, offset=page * TENANTS_PAGE_SIZE)
    if not overviews and page > 0:
        # Страница за пределами данных (арендатор удалён/список изменился
        # между запросами) — откатываемся на первую (см. Phase 9C §M-6).
        await show_tenants(
            callback, PlatformCB(action="tenants", arg="0"), state, session
        )
        return
    if not overviews:
        text = "🏢 Арендаторов пока нет."
    else:
        text = f"🏢 <b>Арендаторы</b> (всего {total})\n\n" + "\n".join(
            f"• {esc(o.name)} ({o.status.value})" for o in overviews
        )
    has_next = (page + 1) * TENANTS_PAGE_SIZE < total
    await edit_message(callback, text, platform_tenants_kb(overviews, page, has_next))
    await callback.answer()


@router.callback_query(PlatformCB.filter(F.action == "tenant"))
async def show_tenant(
    callback: CallbackQuery, callback_data: PlatformCB, session: AsyncSession
) -> None:
    # Сервер-сайд валидация arg: не доверяем строке из callback напрямую,
    # разрешаем tenant через репозиторий/сервис (см. §Callback security).
    tenant_id = parse_uuid(callback_data.arg)
    overview = await TenantManagementService(session).get_tenant(tenant_id) if tenant_id else None
    if overview is None:
        await alert(callback, "Арендатор не найден.")
        return
    await edit_message(callback, _tenant_card_text(overview), platform_tenant_detail_kb(overview))
    await callback.answer()


@router.callback_query(PlatformCB.filter(F.action == "activate"))
async def activate_tenant(
    callback: CallbackQuery, callback_data: PlatformCB, session: AsyncSession
) -> None:
    tenant_id = parse_uuid(callback_data.arg)
    if tenant_id is None or callback.from_user is None:
        await alert(callback, "Некорректный арендатор.")
        return
    service = TenantManagementService(session)
    readiness = await service.activate_tenant(tenant_id, actor_telegram_id=callback.from_user.id)
    if not readiness.is_ready:
        reasons = "\n".join(t(key, "ru") for key in readiness.missing)
        await alert(callback, f"Ещё не готово:\n{reasons}"[:200])
    overview = await service.get_tenant(tenant_id)
    if overview is not None:
        markup = platform_tenant_detail_kb(overview)
        await edit_message(callback, _tenant_card_text(overview), markup)
    if readiness.is_ready:
        await callback.answer("Активирован")


@router.callback_query(PlatformCB.filter(F.action == "suspend"))
async def suspend_tenant(
    callback: CallbackQuery, callback_data: PlatformCB, session: AsyncSession
) -> None:
    tenant_id = parse_uuid(callback_data.arg)
    if tenant_id is None or callback.from_user is None:
        await alert(callback, "Некорректный арендатор.")
        return
    service = TenantManagementService(session)
    try:
        await service.suspend_tenant(tenant_id, actor_telegram_id=callback.from_user.id)
    except TenantLifecycleError:
        await alert(callback, "Нельзя приостановить арендатора в этом статусе.")
        return
    overview = await service.get_tenant(tenant_id)
    if overview is not None:
        markup = platform_tenant_detail_kb(overview)
        await edit_message(callback, _tenant_card_text(overview), markup)
    await callback.answer("Приостановлен")


@router.callback_query(PlatformCB.filter(F.action == "create"))
async def start_create_tenant(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PlatformSG.tenant_name)
    await edit_message(callback, "Введите название нового арендатора:")
    await callback.answer()


@router.message(PlatformSG.tenant_name)
async def finish_create_tenant(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    try:
        name = validate_name(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.clear()
    service = TenantManagementService(session)
    tenant = await service.create_tenant(name=name, actor_telegram_id=message.from_user.id)
    overview = await service.get_tenant(tenant.id)
    await message.answer(
        f"✅ Арендатор создан (ONBOARDING)\n\n{_tenant_card_text(overview)}",
        reply_markup=platform_tenant_detail_kb(overview),
    )
