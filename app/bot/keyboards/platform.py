"""Клавиатуры платформенной админки (Phase 8) — минимальная поверхность,
никаких кнопок оплаты/токенов (см. docs/PLATFORM_CONTROL_PLANE.md §14)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.callbacks import PlatformCB
from app.database.models import TelegramBotIdentity, TenantStatus
from app.services.tenant_management import TenantOverview


def _back(action: str, arg: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="⬅️ Назад", callback_data=PlatformCB(action=action, arg=arg).pack()
    )


def platform_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏢 Арендаторы", callback_data=PlatformCB(action="tenants"))
    builder.adjust(1)
    return builder.as_markup()


def platform_tenants_kb(
    tenants: list[TenantOverview], page: int = 0, has_next: bool = False
) -> InlineKeyboardMarkup:
    """Тот же Previous/Next-паттерн, что и admin-списки (см. Phase 9C §M-6,
    app/bot/keyboards/admin.py::_paginated) — не второй pagination framework,
    просто своя callback-фабрика (PlatformCB, не AdmCB)."""
    builder = InlineKeyboardBuilder()
    for tenant in tenants:
        mark = {
            TenantStatus.ACTIVE: "✅",
            TenantStatus.ONBOARDING: "🚧",
            TenantStatus.SUSPENDED: "⛔",
        }[tenant.status]
        builder.button(
            text=f"{mark} {tenant.name}",
            callback_data=PlatformCB(action="tenant", arg=str(tenant.id)),
        )
    builder.adjust(1)
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=PlatformCB(action="tenants", arg=str(page - 1)).pack()
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="➡️", callback_data=PlatformCB(action="tenants", arg=str(page + 1)).pack()
            )
        )
    if navigation:
        builder.row(*navigation)
    builder.row(
        InlineKeyboardButton(
            text="➕ Создать арендатора", callback_data=PlatformCB(action="create").pack()
        )
    )
    builder.row(_back("menu"))
    return builder.as_markup()


def platform_tenant_detail_kb(tenant: TenantOverview) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if tenant.status == TenantStatus.ACTIVE:
        builder.button(
            text="⛔ Приостановить", callback_data=PlatformCB(action="suspend", arg=str(tenant.id))
        )
    elif tenant.status in (TenantStatus.ONBOARDING, TenantStatus.SUSPENDED):
        builder.button(
            text="✅ Активировать", callback_data=PlatformCB(action="activate", arg=str(tenant.id))
        )
    builder.button(
        text="🤖 Боты", callback_data=PlatformCB(action="bots", arg=str(tenant.id))
    )
    builder.row(_back("tenants"))
    builder.adjust(1)
    return builder.as_markup()


def platform_bots_kb(
    tenant_id: str, bots: list[TelegramBotIdentity]
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for bot in bots:
        mark = "✅" if bot.is_active else "🚫"
        label = f"{mark} {bot.username or bot.telegram_bot_id}"
        builder.button(
            text=label,
            callback_data=PlatformCB(action="bot_toggle", arg=str(bot.telegram_bot_id)),
        )
    builder.row(_back("tenant", tenant_id))
    builder.adjust(1)
    return builder.as_markup()
