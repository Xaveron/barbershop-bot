"""Админ: рабочие часы и исключения из графика."""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_type
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import t
from app.bot.keyboards.admin import (
    back_to_admin_kb,
    barber_picker_kb,
    branch_picker_kb,
    exceptions_kb,
    week_kb,
    weekday_actions_kb,
)
from app.bot.keyboards.callbacks import AdmCB, AdmDayCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import AdminExceptionSG, AdminScheduleSG
from app.bot.utils import alert, edit_message, parse_uuid
from app.config import Settings
from app.database.models import Branch, Permission, StaffMember
from app.database.repositories import BarberRepository, BranchRepository, ScheduleRepository
from app.services.authorization import resolve_accessible_branch_ids
from app.services.schedule import ScheduleService
from app.utils.dt import format_time, today_in, weekday_full
from app.utils.text import esc
from app.utils.validators import ValidationError, validate_date, validate_time_range

logger = logging.getLogger(__name__)
router = Router(name="admin-schedule")
router.message.filter(RequirePermission(Permission.MANAGE_SCHEDULE))
router.callback_query.filter(RequirePermission(Permission.MANAGE_SCHEDULE))

EXCEPTIONS_HORIZON_DAYS = 180


async def _accessible_branch_ids(
    session: AsyncSession, tenant_id: uuid.UUID, staff: StaffMember | None, is_super_admin: bool,
) -> frozenset[uuid.UUID] | None:
    return await resolve_accessible_branch_ids(
        session, tenant_id, staff, is_super_admin=is_super_admin
    )


def _restrict(branches: list[Branch], accessible: frozenset[uuid.UUID] | None) -> list[Branch]:
    """accessible=None означает «без ограничений» (TENANT_OWNER/TENANT_ADMIN/
    платформенный SUPER_ADMIN) — иначе оставляем только доступные сотруднику филиалы
    (см. docs/STAFF_SERVICE_BRANCH_DESIGN.md, RBAC branch-scope enforcement)."""
    if accessible is None:
        return branches
    return [b for b in branches if b.id in accessible]


# --- Рабочие часы -----------------------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "schedule"))
async def pick_barber_for_schedule(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    barbers = await BarberRepository(session, tenant_id).list_all()
    if not barbers:
        await alert(callback, t("admin.schedule.add_barber_first", staff_lang))
        return
    await edit_message(
        callback,
        t("admin.schedule.title_pick_barber", staff_lang),
        barber_picker_kb(barbers, "sch_barber", staff_lang),
    )
    await callback.answer()


async def _enter_barber_schedule(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    barber_id: uuid.UUID,
    is_super_admin: bool,
    lang: str,
) -> None:
    """Общая точка входа после выбора барбера: резолвит его филиалы,
    сужает до доступных сотруднику, авто-выбирает единственный (без нового
    UX для сегодняшних одно-филиальных барберов) либо просит выбрать."""
    barber = await BarberRepository(session, tenant_id).get(barber_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", lang))
        return
    await state.update_data(barber_id=str(barber.id))

    branches = await BranchRepository(session, tenant_id).list_for_barber(barber.id)
    accessible = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    candidates = _restrict(branches, accessible)
    if not candidates:
        await alert(callback, t("admin.schedule.no_accessible_branches", lang))
        return
    if len(candidates) == 1:
        await state.update_data(branch_id=str(candidates[0].id))
        await _show_week_view(
            callback, session, settings, tenant_id, barber.id, candidates[0], lang
        )
        return
    await edit_message(
        callback,
        t("admin.schedule.pick_branch_title", lang, barber=esc(barber.name)),
        branch_picker_kb(candidates, "sch_pick_branch", lang, back="schedule"),
    )


@router.callback_query(AdmCB.filter(F.action == "sch_barber"))
async def show_week(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    await state.clear()
    barber_id = parse_uuid(callback_data.arg)
    if barber_id is None:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return
    await _enter_barber_schedule(
        callback, state, session, settings, tenant_id, staff, barber_id, is_super_admin, staff_lang
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "sch_pick_branch"))
async def pick_branch_for_schedule(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    data = await state.get_data()
    barber_id = parse_uuid(data.get("barber_id", ""))
    branch_id = parse_uuid(callback_data.arg)
    if barber_id is None or branch_id is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return
    branch = await BranchRepository(session, tenant_id).get_active(branch_id)
    accessible = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if (
        branch is None
        or not await BranchRepository(session, tenant_id).barber_works_at_branch(
            barber_id=barber_id, branch_id=branch_id
        )
        or (accessible is not None and branch_id not in accessible)
    ):
        await alert(callback, t("admin.errors.no_rights_or_branch_unavailable", staff_lang))
        return
    await state.update_data(branch_id=str(branch.id))
    await _show_week_view(callback, session, settings, tenant_id, barber_id, branch, staff_lang)
    await callback.answer()


async def _show_week_view(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    barber_id: uuid.UUID,
    branch: Branch,
    lang: str,
) -> None:
    barber = await BarberRepository(session, tenant_id).get(barber_id)
    if barber is None:
        await alert(callback, t("admin.barber.not_found", lang))
        return
    summary = await ScheduleService(session, settings, tenant_id, branch).week_summary(barber.id)
    title = t("admin.schedule.week_title", lang, barber=esc(barber.name), branch=esc(branch.name))
    await edit_message(
        callback,
        f"{title}\n\n{t('admin.schedule.pick_day_prompt', lang)}",
        week_kb(str(barber.id), summary, lang),
    )


@router.callback_query(AdmDayCB.filter())
async def show_weekday(
    callback: CallbackQuery,
    callback_data: AdmDayCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    barber_id = parse_uuid(callback_data.barber)
    barber = await BarberRepository(session, tenant_id).get(barber_id) if barber_id else None
    if barber is None or not 0 <= callback_data.weekday <= 6:
        await alert(callback, t("admin.barber.not_found", staff_lang))
        return
    data = await state.get_data()
    branch_id = parse_uuid(data.get("branch_id", ""))
    if branch_id is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return
    record = await ScheduleRepository(session, tenant_id).get_day(
        barber.id, branch_id, callback_data.weekday
    )
    current = (
        f"{format_time(record.start_time)}-{format_time(record.end_time)}"
        if record
        else t("admin.schedule.day_off", staff_lang)
    )
    await edit_message(
        callback,
        t(
            "admin.schedule.weekday_title",
            staff_lang,
            barber=esc(barber.name),
            weekday=weekday_full(callback_data.weekday, staff_lang),
            current=current,
        ),
        weekday_actions_kb(str(barber.id), callback_data.weekday, staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "sch_set"))
async def ask_hours(
    callback: CallbackQuery, callback_data: AdmCB, state: FSMContext, staff_lang: str
) -> None:
    parsed = _parse_barber_weekday(callback_data.arg)
    if parsed is None:
        await alert(callback, t("admin.schedule.invalid_data", staff_lang))
        return
    barber_id, weekday = parsed
    await state.set_state(AdminScheduleSG.hours)
    await state.update_data(barber_id=str(barber_id), weekday=weekday)
    await edit_message(
        callback,
        t(
            "admin.schedule.set_hours_prompt",
            staff_lang,
            weekday=weekday_full(weekday, staff_lang),
        ),
        back_to_admin_kb(staff_lang, "sch_barber", str(barber_id)),
    )
    await callback.answer()


@router.message(AdminScheduleSG.hours)
async def save_hours(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    try:
        start, end = validate_time_range(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    data = await state.get_data()
    barber_id = parse_uuid(data.get("barber_id", ""))
    branch_id = parse_uuid(data.get("branch_id", ""))
    weekday = int(data.get("weekday", -1))
    if barber_id is None or branch_id is None or not 0 <= weekday <= 6:
        await state.clear()
        await message.answer(t("admin.errors.session_expired", staff_lang))
        return

    branch = await BranchRepository(session, tenant_id).get_active(branch_id)
    if branch is None:
        await state.clear()
        await message.answer(t("admin.branch.not_found", staff_lang))
        return
    try:
        record = await ScheduleRepository(session, tenant_id).set_day(
            barber_id, branch.id, weekday, start, end
        )
        if record is None:
            await session.rollback()
            await message.answer(t("admin.barber.not_found", staff_lang))
            return
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось сохранить график")
        await message.answer(t("admin.schedule.save_failed", staff_lang))
        return

    # Оставляем barber_id/branch_id в состоянии: продолжение редактирования
    # графика (следующий день недели) не должно требовать выбора филиала заново.
    await state.set_state(None)
    await state.update_data(barber_id=str(barber_id), branch_id=str(branch.id))
    summary = await ScheduleService(session, settings, tenant_id, branch).week_summary(barber_id)
    await message.answer(
        t(
            "admin.schedule.hours_saved",
            staff_lang,
            weekday=weekday_full(weekday, staff_lang),
            start=format_time(start),
            end=format_time(end),
        ),
        reply_markup=week_kb(str(barber_id), summary, staff_lang),
    )


@router.callback_query(AdmCB.filter(F.action == "sch_off"))
async def set_day_off(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    parsed = _parse_barber_weekday(callback_data.arg)
    if parsed is None:
        await alert(callback, t("admin.schedule.invalid_data", staff_lang))
        return
    barber_id, weekday = parsed
    data = await state.get_data()
    branch_id = parse_uuid(data.get("branch_id", ""))
    branch = await BranchRepository(session, tenant_id).get_active(branch_id) if branch_id else None
    if branch is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return
    await ScheduleRepository(session, tenant_id).clear_day(barber_id, branch.id, weekday)
    await session.commit()
    summary = await ScheduleService(session, settings, tenant_id, branch).week_summary(barber_id)
    await edit_message(
        callback,
        t("admin.schedule.day_off_saved", staff_lang, weekday=weekday_full(weekday, staff_lang)),
        week_kb(str(barber_id), summary, staff_lang),
    )
    await callback.answer(t("admin.errors.saved", staff_lang))


# --- Исключения -------------------------------------------------------------
@router.callback_query(AdmCB.filter(F.action == "exceptions"))
async def show_exceptions(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    await state.clear()
    accessible = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    branches = _restrict(await BranchRepository(session, tenant_id).list_active(), accessible)
    exceptions: list = []
    branch_names: dict[uuid.UUID, str] = {}
    repository = ScheduleRepository(session, tenant_id)
    for branch in branches:
        # "Сегодня" — по часовому поясу ЭТОГО филиала (Branch.timezone —
        # authoritative, см. Phase 9B §M-3), не settings.tz: у каждого
        # филиала своя граница горизонта показа исключений.
        branch_today = today_in(branch.tz)
        branch_exceptions = await repository.list_exceptions(
            branch_id=branch.id,
            date_from=branch_today,
            date_to=branch_today + timedelta(days=EXCEPTIONS_HORIZON_DAYS),
        )
        exceptions.extend(branch_exceptions)
        branch_names.update({exc.id: branch.name for exc in branch_exceptions})
    exceptions.sort(key=lambda exc: exc.exception_date)

    lines = [t("admin.schedule.title_exceptions", staff_lang) + "\n"]
    if not exceptions:
        lines.append(t("admin.schedule.no_exceptions", staff_lang))
    else:
        all_barbers = await BarberRepository(session, tenant_id).list_all()
        barbers = {barber.id: barber.name for barber in all_barbers}
        multi_branch = len(branches) > 1
        for exception in exceptions:
            scope = (
                t("admin.schedule.exc_scope_whole_branch", staff_lang)
                if exception.is_global
                else barbers.get(
                    exception.barber_id, t("admin.schedule.exc_scope_barber_fallback", staff_lang)
                )
            )
            if multi_branch:
                scope = f"{scope} ({branch_names.get(exception.id, '?')})"
            if exception.is_day_off:
                detail = t("admin.schedule.day_off", staff_lang)
            else:
                detail = (
                    f"{format_time(exception.start_time)}-{format_time(exception.end_time)}"
                    if exception.start_time and exception.end_time
                    else t("admin.exceptions.special_hours", staff_lang)
                )
            lines.append(
                t(
                    "admin.schedule.exc_row",
                    staff_lang,
                    date=exception.exception_date.strftime("%d.%m.%Y"),
                    scope=esc(scope),
                    detail=detail,
                )
            )
        lines.append("\n" + t("admin.schedule.exc_tap_hint", staff_lang))
    await edit_message(callback, "\n".join(lines), exceptions_kb(exceptions, staff_lang))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "exc_add"))
async def add_exception_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    barbers = await BarberRepository(session, tenant_id).list_all()
    await edit_message(
        callback,
        t("admin.schedule.new_exception_title", staff_lang),
        barber_picker_kb(barbers, "exc_who", staff_lang, back="exceptions", with_global=True),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "exc_who"))
async def add_exception_pick_date(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    scope = callback_data.arg
    barber_id = None if scope == "all" else parse_uuid(scope)
    if scope != "all" and barber_id is None:
        await alert(callback, t("admin.schedule.invalid_choice", staff_lang))
        return
    await state.update_data(scope=scope)

    accessible = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if barber_id is None:
        candidates = _restrict(await BranchRepository(session, tenant_id).list_active(), accessible)
    else:
        candidates = _restrict(
            await BranchRepository(session, tenant_id).list_for_barber(barber_id), accessible
        )
    if not candidates:
        await alert(callback, t("admin.schedule.no_accessible_branches_generic", staff_lang))
        return
    if len(candidates) > 1:
        await edit_message(
            callback,
            t("admin.schedule.pick_branch_generic", staff_lang),
            branch_picker_kb(candidates, "exc_pick_branch", staff_lang, back="exceptions"),
        )
        await callback.answer()
        return

    await state.update_data(branch_id=str(candidates[0].id))
    await _ask_exception_date(callback, state, staff_lang)
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "exc_pick_branch"))
async def pick_branch_for_exception(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    data = await state.get_data()
    scope = data.get("scope")
    branch_id = parse_uuid(callback_data.arg)
    if not scope or branch_id is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return
    branch = await BranchRepository(session, tenant_id).get_active(branch_id)
    accessible = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if branch is None or (accessible is not None and branch_id not in accessible):
        await alert(callback, t("admin.errors.no_rights_or_branch_unavailable", staff_lang))
        return
    barber_id = None if scope == "all" else parse_uuid(scope)
    if barber_id is not None and not await BranchRepository(
        session, tenant_id
    ).barber_works_at_branch(barber_id=barber_id, branch_id=branch_id):
        await alert(callback, t("admin.schedule.barber_not_at_branch", staff_lang))
        return
    await state.update_data(branch_id=str(branch.id))
    await _ask_exception_date(callback, state, staff_lang)
    await callback.answer()


async def _ask_exception_date(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.set_state(AdminExceptionSG.date)
    await edit_message(
        callback,
        t("admin.schedule.ask_date_prompt", lang),
        back_to_admin_kb(lang, "exceptions"),
    )


@router.message(AdminExceptionSG.date)
async def add_exception_date(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    # Не доверяем branch_id из состояния молча: филиал должен быть
    # tenant-scoped, активным и доступным ИМЕННО этому сотруднику сейчас —
    # тот же resolve_accessible_branch_ids, что и на шаге выбора филиала
    # (см. Phase 9B §M-3). "Сегодня" считается по часовому поясу ЭТОГО
    # филиала, а не settings.tz.
    data = await state.get_data()
    branch_id = parse_uuid(data.get("branch_id", ""))
    branch = (
        await BranchRepository(session, tenant_id).get_active(branch_id)
        if branch_id is not None
        else None
    )
    accessible = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if branch is None or (accessible is not None and branch.id not in accessible):
        await state.clear()
        await message.answer(t("admin.errors.session_expired", staff_lang))
        return
    try:
        exception_date = validate_date(
            message.text or "",
            lang=staff_lang,
            not_before=today_in(branch.tz),
            max_days_ahead=EXCEPTIONS_HORIZON_DAYS,
        )
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(date=exception_date.isoformat())
    await state.set_state(AdminExceptionSG.mode)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("admin.schedule.mode_off", staff_lang),
        callback_data=AdmCB(action="exc_mode", arg="off"),
    )
    builder.button(
        text=t("admin.schedule.mode_hours", staff_lang),
        callback_data=AdmCB(action="exc_mode", arg="hours"),
    )
    builder.adjust(1)
    await message.answer(
        t(
            "admin.schedule.date_mode_prompt",
            staff_lang,
            date=exception_date.strftime("%d.%m.%Y"),
        ),
        reply_markup=builder.as_markup(),
    )


@router.callback_query(AdminExceptionSG.mode, AdmCB.filter(F.action == "exc_mode"))
async def add_exception_mode(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    if callback_data.arg == "hours":
        await state.set_state(AdminExceptionSG.hours)
        await edit_message(
            callback,
            t("admin.schedule.ask_hours_prompt", staff_lang),
            back_to_admin_kb(staff_lang, "exceptions"),
        )
        await callback.answer()
        return

    saved = await _save_exception(state, session, tenant_id, is_day_off=True)
    if not saved:
        await alert(callback, t("admin.schedule.exception_save_failed", staff_lang))
        return
    await state.clear()
    await edit_message(
        callback,
        t("admin.schedule.exception_saved", staff_lang),
        back_to_admin_kb(staff_lang, "exceptions"),
    )
    await callback.answer(t("admin.errors.saved", staff_lang))


@router.message(AdminExceptionSG.hours)
async def add_exception_hours(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    try:
        start, end = validate_time_range(message.text or "", lang=staff_lang)
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    saved = await _save_exception(state, session, tenant_id, is_day_off=False, start=start, end=end)
    await state.clear()
    if not saved:
        await message.answer(f"⚠️ {t('admin.schedule.exception_save_failed', staff_lang)}")
        return
    await message.answer(
        t(
            "admin.schedule.exception_saved_hours",
            staff_lang,
            start=format_time(start),
            end=format_time(end),
        ),
        reply_markup=back_to_admin_kb(staff_lang, "exceptions"),
    )


@router.callback_query(AdmCB.filter(F.action == "exc_del"))
async def delete_exception(
    callback: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    is_super_admin: bool,
    staff_lang: str,
) -> None:
    exception_id = parse_uuid(callback_data.arg)
    repository = ScheduleRepository(session, tenant_id)
    exception = await repository.get_exception(exception_id) if exception_id else None
    if exception is None:
        await alert(callback, t("admin.schedule.exception_not_found", staff_lang))
        return
    accessible = await _accessible_branch_ids(session, tenant_id, staff, is_super_admin)
    if accessible is not None and exception.branch_id not in accessible:
        await alert(callback, t("common.no_rights", staff_lang))
        return
    await repository.delete_exception(exception)
    await session.commit()
    await callback.answer(t("admin.common.deleted_toast", staff_lang))
    # Аргументы по имени: позиционный вызов здесь ранее подставлял settings
    # на место tenant_id (обнаружено по ходу Phase 9F, никогда не
    # срабатывало бы корректно — этот путь не был покрыт тестами).
    await show_exceptions(
        callback,
        state=state,
        session=session,
        tenant_id=tenant_id,
        staff=staff,
        is_super_admin=is_super_admin,
        staff_lang=staff_lang,
    )


# --- Вспомогательное --------------------------------------------------------
def _parse_barber_weekday(raw: str) -> tuple[uuid.UUID, int] | None:
    parts = raw.split("|")
    if len(parts) != 2:
        return None
    barber_id = parse_uuid(parts[0])
    if barber_id is None or not parts[1].isdigit():
        return None
    weekday = int(parts[1])
    if not 0 <= weekday <= 6:
        return None
    return barber_id, weekday


async def _save_exception(
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    is_day_off: bool,
    start=None,
    end=None,
) -> bool:
    data = await state.get_data()
    scope = data.get("scope")
    raw_date = data.get("date")
    branch_id = parse_uuid(data.get("branch_id", ""))
    if not scope or not raw_date or branch_id is None:
        return False
    barber_id = None if scope == "all" else parse_uuid(scope)
    if scope != "all" and barber_id is None:
        return False

    try:
        saved = await ScheduleRepository(session, tenant_id).upsert_exception(
            branch_id=branch_id,
            barber_id=barber_id,
            exception_date=date_type.fromisoformat(raw_date),
            is_day_off=is_day_off,
            start_time=start,
            end_time=end,
        )
        if saved is None:
            await session.rollback()
            return False
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось сохранить исключение")
        return False
    return True
