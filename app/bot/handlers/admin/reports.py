"""Админ: статистика, клиенты, экспорт CSV."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.billing_ui import describe_billing_error
from app.bot.i18n import t
from app.bot.keyboards.admin import back_to_admin_kb, clients_kb, export_periods_kb
from app.bot.keyboards.callbacks import AdmCB
from app.bot.utils import alert, edit_message
from app.config import Settings
from app.database.models import Feature, Permission, StaffMember
from app.database.repositories import UserRepository
from app.services.authorization import (
    AuthorizationError,
    AuthorizationService,
    resolve_accessible_branch_ids,
)
from app.services.billing import EntitlementService, FeatureNotAvailable
from app.services.export import ExportService
from app.services.stats import StatsService
from app.utils.dt import now_utc
from app.utils.text import esc, money

logger = logging.getLogger(__name__)
router = Router(name="admin-reports")
# Нет общего router-level Permission-фильтра (см. Phase 9B §M-4): «Клиенты»
# и «Статистика»/«Экспорт» защищены РАЗНЫМИ правами (VIEW_CUSTOMERS vs
# VIEW_ANALYTICS/MANAGE_CUSTOMERS) — единого «минимального общего» права нет.
# Базовый допуск «это вообще сотрудник арендатора» уже обеспечен IsStaff() на
# уровне build_admin_router(); каждый хендлер здесь проверяет своё право
# инлайн, тем же паттерном, что admin/staff.py.

CLIENTS_PAGE_SIZE = 10
MAX_EXPORT_DAYS = 3650


@router.callback_query(AdmCB.filter(F.action == "stats"))
async def show_stats(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    try:
        AuthorizationService.require(
            staff, Permission.VIEW_ANALYTICS, is_super_admin=is_super_admin
        )
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    await state.clear()
    try:
        await EntitlementService(session, tenant_id).require_feature(Feature.ANALYTICS)
    except FeatureNotAvailable as exc:
        await alert(callback, describe_billing_error(exc, staff_lang))
        return
    branch_ids = await resolve_accessible_branch_ids(
        session, tenant_id, staff, is_super_admin=is_super_admin
    )
    stats = await StatsService(session, settings, tenant_id).collect(branch_ids=branch_ids)
    lines = [
        t("admin.stats.title", staff_lang) + "\n",
        t("admin.stats.total_appointments", staff_lang, value=stats.total_appointments),
        t("admin.stats.upcoming", staff_lang, value=stats.upcoming_appointments),
        t("admin.stats.today", staff_lang, value=stats.today_appointments),
        t("admin.stats.this_month", staff_lang, value=stats.month_appointments),
        t("admin.stats.cancelled_month", staff_lang, value=stats.cancelled_month),
        t("admin.stats.clients", staff_lang, value=stats.clients),
        "",
        t("admin.stats.revenue_today", staff_lang, value=money(stats.revenue_today)),
        t("admin.stats.revenue_month", staff_lang, value=money(stats.revenue_month)),
    ]
    if stats.top_services:
        lines.append("\n" + t("admin.stats.top_services_header", staff_lang))
        for name, count, revenue in stats.top_services:
            lines.append(f"• {esc(name)}: {count} — {money(revenue)}")
    if stats.top_barbers:
        lines.append("\n" + t("admin.stats.top_barbers_header", staff_lang))
        for name, count, revenue in stats.top_barbers:
            lines.append(f"• {esc(name)}: {count} — {money(revenue)}")
    await edit_message(callback, "\n".join(lines), back_to_admin_kb(staff_lang, "menu"))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "clients"))
async def show_clients(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    # Список клиентов — отдельное от аналитики право (см. Phase 9B §M-4):
    # RECEPTIONIST/BARBER имеют VIEW_CUSTOMERS, но не VIEW_ANALYTICS, и
    # раньше вообще не могли открыть этот экран, хотя роль явно на это
    # рассчитана (docs/RBAC_DESIGN.md).
    try:
        AuthorizationService.require(
            staff, Permission.VIEW_CUSTOMERS, is_super_admin=is_super_admin
        )
    except AuthorizationError:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    branch_ids = await resolve_accessible_branch_ids(
        session, tenant_id, staff, is_super_admin=is_super_admin
    )
    repository = UserRepository(session, tenant_id)
    total = await repository.count(branch_ids=branch_ids)
    rows = await repository.list_with_appointment_counts(
        limit=CLIENTS_PAGE_SIZE, offset=page * CLIENTS_PAGE_SIZE, branch_ids=branch_ids
    )
    if not rows:
        await edit_message(
            callback, t("admin.clients.empty", staff_lang), back_to_admin_kb(staff_lang, "menu")
        )
        await callback.answer()
        return
    lines = [t("admin.clients.list_title", staff_lang, total=total) + "\n"]
    for user, count in rows:
        blocked = " 🚫" if user.is_blocked else ""
        lines.append(
            t(
                "admin.clients.row",
                staff_lang,
                name=esc(user.display_name),
                count=count,
                blocked=blocked,
                telegram_id=f"<code>{user.telegram_id}</code>",
            )
        )
    has_next = (page + 1) * CLIENTS_PAGE_SIZE < total
    await edit_message(callback, "\n".join(lines), clients_kb(page, has_next, staff_lang))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "export"))
async def choose_export_period(
    callback: CallbackQuery,
    state: FSMContext,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    # Тот же MANAGE_CUSTOMERS, что и сам export_do (см. ниже) — не показываем
    # выбор периода тому, кто всё равно будет отклонён на следующем шаге.
    try:
        AuthorizationService.require(
            staff, Permission.MANAGE_CUSTOMERS, is_super_admin=is_super_admin
        )
    except AuthorizationError:
        await alert(callback, t("admin.export.no_rights", staff_lang))
        return
    await state.clear()
    await edit_message(
        callback,
        t("admin.export.title", staff_lang),
        export_periods_kb(staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "export_do"))
async def export_csv(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    # Массовая выгрузка имён/телефонов клиентов в CSV чувствительнее
    # просмотра сводки в чате — MANAGE_CUSTOMERS, не VIEW_ANALYTICS/
    # VIEW_CUSTOMERS (см. Phase 9B §M-4: сегодня MANAGE_CUSTOMERS есть только
    # у ролей, уже имеющих и VIEW_ANALYTICS, так что фактическое поведение
    # экспорта не изменилось — просто больше не зависит от router-level
    # фильтра, которого здесь больше нет).
    try:
        AuthorizationService.require(
            staff, Permission.MANAGE_CUSTOMERS, is_super_admin=is_super_admin
        )
    except AuthorizationError:
        await alert(callback, t("admin.export.no_rights", staff_lang))
        return
    try:
        await EntitlementService(session, tenant_id).require_feature(Feature.CSV_EXPORT)
    except FeatureNotAvailable as exc:
        await alert(callback, describe_billing_error(exc, staff_lang))
        return

    now = now_utc()
    if callback_data.arg == "all":
        start = now - timedelta(days=3650)
        label = t("admin.export.period_all", staff_lang)
    elif callback_data.arg.isdigit():
        # Ограничиваем сверху: timedelta не переживёт подделанный аргумент вида 10**15.
        days = min(int(callback_data.arg), MAX_EXPORT_DAYS)
        start = now - timedelta(days=days)
        label = t("admin.export.period_days", staff_lang, days=days)
    else:
        await alert(callback, t("admin.export.invalid_period", staff_lang))
        return

    end = now + timedelta(days=3650)
    branch_ids = await resolve_accessible_branch_ids(
        session, tenant_id, staff, is_super_admin=is_super_admin
    )
    payload = await ExportService(session, settings, tenant_id).appointments_csv(
        start=start, end=end, branch_ids=branch_ids
    )
    filename = f"appointments_{now.strftime('%Y%m%d_%H%M')}.csv"
    document = BufferedInputFile(payload, filename=filename)

    if callback.message is not None:
        await callback.message.answer_document(
            document,
            caption=t("admin.export.caption", staff_lang, label=label),
            reply_markup=back_to_admin_kb(staff_lang, "menu"),
        )
    await callback.answer(t("admin.export.sent_toast", staff_lang))
