"""Админ: экран «Тариф» — только просмотр (см. docs/BILLING_DESIGN.md §Admin UX).

Гейтится MANAGE_SUBSCRIPTION (Phase 2, уже выдан только TENANT_OWNER) — ничего
нового не изобретается. Нет кнопки оплаты и нет смены тарифа для владельца.
Платформенный оператор (Phase 8, data["is_super_admin"] — см.
app/services/platform_authorization.py) дополнительно видит минимальный
dev-инструмент смены тарифа арендатора — это не подменяет и не расширяет
MANAGE_SUBSCRIPTION, а отдельная, явно обособленная проверка."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.billing_ui import feature_label, limit_label, status_label
from app.bot.i18n import t
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.utils import alert, edit_message
from app.database.models import Feature, LimitKey, Permission
from app.database.repositories import PlanRepository
from app.services.billing import LimitService, SubscriptionService
from app.utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="admin-billing")
router.message.filter(RequirePermission(Permission.MANAGE_SUBSCRIPTION))
router.callback_query.filter(RequirePermission(Permission.MANAGE_SUBSCRIPTION))


async def _render_billing_text(session: AsyncSession, tenant_id: uuid.UUID, lang: str) -> str:
    subscription = await SubscriptionService(session, tenant_id).get_or_create_default()
    plan = subscription.plan
    lines = [
        t("billing.screen_title", lang),
        "",
        t("billing.current_plan", lang, plan_name=esc(plan.name)),
        t("billing.subscription_status", lang, status=status_label(subscription.status, lang)),
        "",
        t("billing.features_header", lang),
    ]
    plan_features = {pf.feature for pf in plan.features}
    for feature in Feature:
        key = "billing.feature_line_on" if feature in plan_features else "billing.feature_line_off"
        lines.append(t(key, lang, feature_name=feature_label(feature, lang)))
    lines.append("")
    lines.append(t("billing.limits_header", lang))
    limit_service = LimitService(session, tenant_id)
    for limit_key in LimitKey:
        maximum = await limit_service.get_limit(limit_key)
        current = await limit_service.get_usage(limit_key)
        name = limit_label(limit_key, lang)
        if maximum is None:
            lines.append(t("billing.limit_line_unlimited", lang, limit_name=name, current=current))
        else:
            lines.append(
                t("billing.limit_line", lang, limit_name=name, current=current, maximum=maximum)
            )
    return "\n".join(lines)


async def _billing_kb(
    session: AsyncSession, *, is_super_admin: bool, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_super_admin:
        for plan in await PlanRepository(session).list_all():
            builder.button(
                text=t("billing.dev_change_plan_btn", lang, plan_name=esc(plan.name)),
                callback_data=AdmCB(action="billing_set", arg=plan.code),
            )
        builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=AdmCB(action="menu").pack()))
    return builder.as_markup()


@router.callback_query(AdmCB.filter(F.action == "billing"))
async def show_billing(
    callback: CallbackQuery,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
    is_super_admin: bool,
) -> None:
    text = await _render_billing_text(session, tenant_id, lang)
    markup = await _billing_kb(session, is_super_admin=is_super_admin, lang=lang)
    await edit_message(callback, text, markup)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "billing_set"))
async def dev_change_plan(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    lang: str,
    is_super_admin: bool,
) -> None:
    if not is_super_admin or callback.from_user is None:
        await alert(callback, t("common.no_rights", lang))
        return
    try:
        subscription = await SubscriptionService(session, tenant_id).change_plan(
            plan_code=callback_data.arg, actor_telegram_id=callback.from_user.id
        )
    except ValueError:
        logger.exception("Не удалось сменить тариф арендатора %s", tenant_id)
        await alert(callback, t("billing.try_again", lang))
        return
    await alert(callback, t("billing.plan_changed", lang, plan_name=esc(subscription.plan.name)))
    text = await _render_billing_text(session, tenant_id, lang)
    markup = await _billing_kb(session, is_super_admin=is_super_admin, lang=lang)
    await edit_message(callback, text, markup)
