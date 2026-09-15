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
from app.bot.keyboards.admin import back_to_admin_kb, clients_kb, export_periods_kb
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.utils import alert, edit_message
from app.config import Settings
from app.database.models import Feature, Permission, StaffMember
from app.database.repositories import UserRepository
from app.services.authorization import AuthorizationError, AuthorizationService
from app.services.billing import EntitlementService, FeatureNotAvailable
from app.services.export import ExportService
from app.services.stats import StatsService
from app.utils.dt import now_utc
from app.utils.text import esc, money

logger = logging.getLogger(__name__)
router = Router(name="admin-reports")
router.message.filter(RequirePermission(Permission.VIEW_ANALYTICS))
router.callback_query.filter(RequirePermission(Permission.VIEW_ANALYTICS))

CLIENTS_PAGE_SIZE = 10
MAX_EXPORT_DAYS = 3650


@router.callback_query(AdmCB.filter(F.action == "stats"))
async def show_stats(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    lang: str,
) -> None:
    await state.clear()
    try:
        await EntitlementService(session, tenant_id).require_feature(Feature.ANALYTICS)
    except FeatureNotAvailable as exc:
        await alert(callback, describe_billing_error(exc, lang))
        return
    stats = await StatsService(session, settings, tenant_id).collect()
    lines = [
        "📊 <b>Статистика</b>\n",
        f"📅 Всего записей: <b>{stats.total_appointments}</b>",
        f"⏭ Предстоящих: <b>{stats.upcoming_appointments}</b>",
        f"📆 Сегодня: <b>{stats.today_appointments}</b>",
        f"🗓 В этом месяце: <b>{stats.month_appointments}</b>",
        f"🚫 Отменено за месяц: <b>{stats.cancelled_month}</b>",
        f"👥 Клиентов: <b>{stats.clients}</b>",
        "",
        f"💰 Выручка сегодня: <b>{money(stats.revenue_today)}</b>",
        f"💰 Выручка за месяц: <b>{money(stats.revenue_month)}</b>",
    ]
    if stats.top_services:
        lines.append("\n🔥 <b>Популярные услуги (месяц)</b>")
        for name, count, revenue in stats.top_services:
            lines.append(f"• {esc(name)}: {count} — {money(revenue)}")
    if stats.top_barbers:
        lines.append("\n👨‍💈 <b>Барберы (месяц)</b>")
        for name, count, revenue in stats.top_barbers:
            lines.append(f"• {esc(name)}: {count} — {money(revenue)}")
    await edit_message(callback, "\n".join(lines), back_to_admin_kb("menu"))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "clients"))
async def show_clients(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    await state.clear()
    page = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    repository = UserRepository(session, tenant_id)
    total = await repository.count()
    rows = await repository.list_with_appointment_counts(
        limit=CLIENTS_PAGE_SIZE, offset=page * CLIENTS_PAGE_SIZE
    )
    if not rows:
        await edit_message(callback, "👥 Клиентов пока нет.", back_to_admin_kb("menu"))
        await callback.answer()
        return
    lines = [f"👥 <b>Клиенты</b> (всего {total})\n"]
    for user, count in rows:
        blocked = " 🚫" if user.is_blocked else ""
        lines.append(
            f"• {esc(user.display_name)} — {count} зап.{blocked}\n"
            f"  <code>{user.telegram_id}</code>"
        )
    has_next = (page + 1) * CLIENTS_PAGE_SIZE < total
    await edit_message(callback, "\n".join(lines), clients_kb(page, has_next))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "export"))
async def choose_export_period(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_message(
        callback,
        "📥 <b>Экспорт записей в CSV</b>\n\nВыберите период:",
        export_periods_kb(),
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
    lang: str,
) -> None:
    # Доп. проверка сверх VIEW_ANALYTICS на уровне роутера: массовая выгрузка
    # имён/телефонов клиентов в CSV чувствительнее просмотра сводки в чате —
    # роль с одним VIEW_ANALYTICS (например MANAGER) не должна автоматически
    # получать право на выгрузку персональных данных (см. docs/RBAC_DESIGN.md §5).
    try:
        AuthorizationService.require(
            staff, Permission.MANAGE_CUSTOMERS, is_super_admin=is_super_admin
        )
    except AuthorizationError:
        await alert(callback, "Недостаточно прав для экспорта.")
        return
    try:
        await EntitlementService(session, tenant_id).require_feature(Feature.CSV_EXPORT)
    except FeatureNotAvailable as exc:
        await alert(callback, describe_billing_error(exc, lang))
        return

    now = now_utc()
    if callback_data.arg == "all":
        start = now - timedelta(days=3650)
        label = "все записи"
    elif callback_data.arg.isdigit():
        # Ограничиваем сверху: timedelta не переживёт подделанный аргумент вида 10**15.
        days = min(int(callback_data.arg), MAX_EXPORT_DAYS)
        start = now - timedelta(days=days)
        label = f"за {days} дн."
    else:
        await alert(callback, "Некорректный период.")
        return

    end = now + timedelta(days=3650)
    payload = await ExportService(session, settings, tenant_id).appointments_csv(
        start=start, end=end
    )
    filename = f"appointments_{now.strftime('%Y%m%d_%H%M')}.csv"
    document = BufferedInputFile(payload, filename=filename)

    if callback.message is not None:
        await callback.message.answer_document(
            document,
            caption=f"📥 Экспорт записей ({label})",
            reply_markup=back_to_admin_kb("menu"),
        )
    await callback.answer("Файл отправлен")
