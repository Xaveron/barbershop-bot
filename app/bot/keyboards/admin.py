"""Клавиатуры админ-панели."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.i18n import LANGUAGE_NAMES, t
from app.bot.keyboards.callbacks import AdmCB, AdmDayCB, NavCB
from app.database.models import (
    Appointment,
    Barber,
    Branch,
    Role,
    ScheduleException,
    Service,
    StaffMember,
)
from app.utils.dt import format_time, to_local, weekday_full
from app.utils.text import money

_ROLE_KEYS: dict[Role, str] = {
    Role.TENANT_OWNER: "admin.role.tenant_owner",
    Role.TENANT_ADMIN: "admin.role.tenant_admin",
    Role.MANAGER: "admin.role.manager",
    Role.RECEPTIONIST: "admin.role.receptionist",
    Role.BARBER: "admin.role.barber",
}


def role_label(role: Role, lang: str) -> str:
    key = _ROLE_KEYS.get(role)
    return t(key, lang) if key else role.value


# TENANT_OWNER никогда не предлагается как назначаемая роль через этот UI —
# владелец на арендатора один, и он назначается только онбордингом/платформой
# (см. Phase 9A §H-1, docs/PLATFORM_CONTROL_PLANE.md §Owner bootstrap).
ASSIGNABLE_ROLES: tuple[Role, ...] = (
    Role.TENANT_ADMIN,
    Role.MANAGER,
    Role.RECEPTIONIST,
    Role.BARBER,
)


def _back(lang: str, action: str, arg: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=t("admin.btn.back", lang), callback_data=AdmCB(action=action, arg=arg).pack()
    )


def admin_menu_kb(
    lang: str,
    *,
    can_manage_branches: bool = False,
    can_view_staff: bool = False,
    can_manage_subscription: bool = False,
    can_manage_settings: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("admin.menu.services", lang), callback_data=AdmCB(action="services"))
    builder.button(text=t("admin.menu.barbers", lang), callback_data=AdmCB(action="barbers"))
    builder.button(text=t("admin.menu.schedule", lang), callback_data=AdmCB(action="schedule"))
    builder.button(
        text=t("admin.menu.exceptions", lang), callback_data=AdmCB(action="exceptions")
    )
    builder.button(
        text=t("admin.menu.appointments", lang), callback_data=AdmCB(action="appts", arg="0")
    )
    builder.button(
        text=t("admin.menu.clients", lang), callback_data=AdmCB(action="clients", arg="0")
    )
    builder.button(text=t("admin.menu.stats", lang), callback_data=AdmCB(action="stats"))
    builder.button(text=t("admin.menu.export", lang), callback_data=AdmCB(action="export"))
    if can_manage_branches:
        builder.button(text=t("admin.menu.branches", lang), callback_data=AdmCB(action="branches"))
    if can_view_staff:
        builder.button(text=t("admin.menu.staff", lang), callback_data=AdmCB(action="staff"))
    if can_manage_subscription:
        builder.button(text=t("admin.menu.billing", lang), callback_data=AdmCB(action="billing"))
    if can_manage_settings:
        builder.button(text=t("admin.menu.settings", lang), callback_data=AdmCB(action="settings"))
    # Личный язык интерфейса (Phase 9E §11) — доступен ЛЮБОМУ активному
    # сотруднику, не гейтится MANAGE_SETTINGS (это персональная настройка,
    # а не настройка арендатора, см. app/bot/handlers/admin/language.py).
    builder.button(text=t("admin.menu.my_language", lang), callback_data=AdmCB(action="my_lang"))
    builder.button(text=t("admin.menu.back_to_menu", lang), callback_data=NavCB(to="main"))
    builder.adjust(2, 2, 2, 2, 1, 1, 1, 1, 1)
    return builder.as_markup()


def _paginated(
    builder: InlineKeyboardBuilder, action: str, page: int, has_next: bool
) -> None:
    """Общий Previous/Next-паттерн, переиспользуемый для всех admin-списков
    (см. admin_appointments_kb/clients_kb, Phase 7/9A) и Phase 9C §M-6:
    staff/branches/barbers/services/platform-tenants — один и тот же
    механизм, а не второй pagination framework. Стрелки — не текст, языковой
    параметр им не нужен (Phase 9F §Task 4: pagination controls остаются
    языко-независимыми символами)."""
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=AdmCB(action=action, arg=str(page - 1)).pack()
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="➡️", callback_data=AdmCB(action=action, arg=str(page + 1)).pack()
            )
        )
    if navigation:
        builder.row(*navigation)


def admin_branches_kb(
    branches: Sequence[Branch], lang: str, page: int = 0, has_next: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for branch in branches:
        mark = "" if branch.is_active else "🚫 "
        builder.button(
            text=f"{mark}📍 {branch.name}",
            callback_data=AdmCB(action="brh", arg=str(branch.id)),
        )
    builder.adjust(1)
    _paginated(builder, "branches", page, has_next)
    builder.row(
        InlineKeyboardButton(
            text=t("admin.branches.add", lang), callback_data=AdmCB(action="brh_add").pack()
        )
    )
    builder.row(_back(lang, "menu"))
    return builder.as_markup()


def admin_branch_kb(branch: Branch, lang: str) -> InlineKeyboardMarkup:
    bid = str(branch.id)
    builder = InlineKeyboardBuilder()
    builder.button(text=t("admin.btn.name", lang), callback_data=AdmCB(action="brh_name", arg=bid))
    builder.button(
        text=t("admin.branch.address", lang), callback_data=AdmCB(action="brh_addr", arg=bid)
    )
    builder.button(
        text=t("admin.btn.hide", lang) if branch.is_active else t("admin.btn.show", lang),
        callback_data=AdmCB(action="brh_toggle", arg=bid),
    )
    builder.button(text=t("admin.branch.back", lang), callback_data=AdmCB(action="branches"))
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def admin_staff_kb(
    staff_list: Sequence[StaffMember], lang: str, page: int = 0, has_next: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for staff in staff_list:
        mark = "" if staff.is_active else "🚫 "
        builder.button(
            text=f"{mark}{staff.telegram_id} · {role_label(staff.role, lang)}",
            callback_data=AdmCB(action="stf", arg=str(staff.id)),
        )
    builder.adjust(1)
    _paginated(builder, "staff", page, has_next)
    builder.row(
        InlineKeyboardButton(
            text=t("admin.staff.add", lang), callback_data=AdmCB(action="stf_add").pack()
        )
    )
    builder.row(_back(lang, "menu"))
    return builder.as_markup()


def admin_staff_card_kb(
    staff: StaffMember, branches: Sequence[Branch], assigned_ids: set, lang: str
) -> InlineKeyboardMarkup:
    """Список филиалов с переключателем показывается только для ролей с
    ресурсным сужением доступа (MANAGER/RECEPTIONIST/BARBER) — у
    TENANT_OWNER/TENANT_ADMIN доступ ко всем филиалам и без единой строки
    staff_branches (см. docs/RBAC_DESIGN.md §6). Кнопки «Роль»/«Деактивировать»
    показываются и для владельца — защита единственного владельца живёт в
    сервисном слое (StaffService._assert_not_sole_active_owner), а не
    скрытием кнопки (см. Phase 9A §H-2)."""
    builder = InlineKeyboardBuilder()
    if staff.role in (Role.MANAGER, Role.RECEPTIONIST, Role.BARBER):
        for branch in branches:
            mark = "✅" if branch.id in assigned_ids else "⬜"
            builder.button(
                text=f"{mark} {branch.name}",
                callback_data=AdmCB(action="stf_branch", arg=str(branch.id)),
            )
    builder.button(
        text=t("admin.staff.role", lang),
        callback_data=AdmCB(action="stf_role_pick", arg=str(staff.id)),
    )
    if staff.is_active:
        builder.button(
            text=t("admin.staff.deactivate", lang),
            callback_data=AdmCB(action="stf_deact", arg=str(staff.id)),
        )
    builder.button(text=t("admin.staff.back", lang), callback_data=AdmCB(action="staff"))
    builder.adjust(1)
    return builder.as_markup()


def staff_add_role_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for role in ASSIGNABLE_ROLES:
        builder.button(
            text=role_label(role, lang), callback_data=AdmCB(action="stf_add_role", arg=role.value)
        )
    builder.button(text=t("admin.btn.cancel", lang), callback_data=AdmCB(action="staff"))
    builder.adjust(1)
    return builder.as_markup()


def confirm_add_staff_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("admin.btn.create", lang), callback_data=AdmCB(action="stf_add_confirm"))
    builder.button(text=t("admin.btn.cancel", lang), callback_data=AdmCB(action="staff"))
    builder.adjust(1)
    return builder.as_markup()


def staff_change_role_kb(staff_id: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for role in ASSIGNABLE_ROLES:
        builder.button(
            text=role_label(role, lang),
            callback_data=AdmCB(action="stf_role_set", arg=f"{staff_id}|{role.value}"),
        )
    builder.button(text=t("admin.btn.back", lang), callback_data=AdmCB(action="stf", arg=staff_id))
    builder.adjust(1)
    return builder.as_markup()


def confirm_role_change_kb(staff_id: str, role: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("admin.btn.confirm", lang),
        callback_data=AdmCB(action="stf_role_confirm", arg=f"{staff_id}|{role}"),
    )
    builder.button(
        text=t("admin.btn.cancel", lang),
        callback_data=AdmCB(action="stf", arg=staff_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def confirm_staff_deactivate_kb(staff_id: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("admin.staff.deactivate_confirm", lang),
        callback_data=AdmCB(action="stf_deact_ok", arg=staff_id),
    )
    builder.button(
        text=t("admin.btn.cancel", lang),
        callback_data=AdmCB(action="stf", arg=staff_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_services_kb(
    services: Sequence[Service], lang: str, page: int = 0, has_next: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in services:
        mark = "" if service.is_active else "🚫 "
        builder.button(
            text=f"{mark}{service.name} · {money(service.price, service.currency)}",
            callback_data=AdmCB(action="svc", arg=str(service.id)),
        )
    builder.adjust(1)
    _paginated(builder, "services", page, has_next)
    builder.row(
        InlineKeyboardButton(
            text=t("admin.services.add", lang), callback_data=AdmCB(action="svc_add").pack()
        )
    )
    builder.row(_back(lang, "menu"))
    return builder.as_markup()


def admin_service_kb(service: Service, lang: str) -> InlineKeyboardMarkup:
    sid = str(service.id)
    builder = InlineKeyboardBuilder()
    builder.button(text=t("admin.btn.name", lang), callback_data=AdmCB(action="svc_name", arg=sid))
    builder.button(
        text=t("admin.service.duration", lang), callback_data=AdmCB(action="svc_dur", arg=sid)
    )
    builder.button(
        text=t("admin.service.price", lang), callback_data=AdmCB(action="svc_price", arg=sid)
    )
    builder.button(
        text=t("admin.btn.description", lang), callback_data=AdmCB(action="svc_desc", arg=sid)
    )
    builder.button(
        text=t("admin.label.branches", lang), callback_data=AdmCB(action="svc_branches", arg=sid)
    )
    builder.button(
        text=t("admin.btn.hide", lang) if service.is_active else t("admin.btn.show", lang),
        callback_data=AdmCB(action="svc_toggle", arg=sid),
    )
    builder.button(text=t("admin.btn.delete", lang), callback_data=AdmCB(action="svc_del", arg=sid))
    builder.button(text=t("admin.service.back", lang), callback_data=AdmCB(action="services"))
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def admin_service_branches_kb(
    service: Service, branches: Sequence[Branch], available_ids: set, lang: str
) -> InlineKeyboardMarkup:
    """✅ означает «доступна» — либо явно включена, либо (чаще) просто нет
    строки branch_services (opt-out по умолчанию, см.
    docs/STAFF_SERVICE_BRANCH_DESIGN.md)."""
    builder = InlineKeyboardBuilder()
    for branch in branches:
        mark = "✅" if branch.id in available_ids else "🚫"
        builder.button(
            text=f"{mark} {branch.name}",
            callback_data=AdmCB(action="svc_branch", arg=str(branch.id)),
        )
    builder.button(
        text=t("admin.btn.back", lang), callback_data=AdmCB(action="svc", arg=str(service.id))
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_barbers_kb(
    barbers: Sequence[Barber], lang: str, page: int = 0, has_next: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for barber in barbers:
        mark = "" if barber.is_active else "🚫 "
        builder.button(
            text=f"{mark}{barber.name}",
            callback_data=AdmCB(action="brb", arg=str(barber.id)),
        )
    builder.adjust(1)
    _paginated(builder, "barbers", page, has_next)
    builder.row(
        InlineKeyboardButton(
            text=t("admin.barbers.add", lang), callback_data=AdmCB(action="brb_add").pack()
        )
    )
    builder.row(_back(lang, "menu"))
    return builder.as_markup()


def admin_barber_kb(barber: Barber, lang: str) -> InlineKeyboardMarkup:
    bid = str(barber.id)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("admin.barber.name", lang),
        callback_data=AdmCB(action="brb_name", arg=bid),
    )
    builder.button(
        text=t("admin.btn.description", lang), callback_data=AdmCB(action="brb_desc", arg=bid)
    )
    builder.button(
        text=t("admin.menu.schedule", lang),
        callback_data=AdmCB(action="sch_barber", arg=bid),
    )
    builder.button(
        text=t("admin.label.branches", lang), callback_data=AdmCB(action="brb_branches", arg=bid)
    )
    builder.button(
        text=t("admin.btn.hide", lang) if barber.is_active else t("admin.btn.show", lang),
        callback_data=AdmCB(action="brb_toggle", arg=bid),
    )
    builder.button(text=t("admin.btn.delete", lang), callback_data=AdmCB(action="brb_del", arg=bid))
    builder.button(text=t("admin.barber.back", lang), callback_data=AdmCB(action="barbers"))
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def admin_barber_branches_kb(
    barber: Barber, branches: Sequence[Branch], assigned_ids: set, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for branch in branches:
        mark = "✅" if branch.id in assigned_ids else "⬜"
        builder.button(
            text=f"{mark} {branch.name}",
            callback_data=AdmCB(action="brb_branch", arg=str(branch.id)),
        )
    builder.button(
        text=t("admin.btn.back", lang), callback_data=AdmCB(action="brb", arg=str(barber.id))
    )
    builder.adjust(1)
    return builder.as_markup()


def confirm_delete_kb(action: str, arg: str, back_action: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("admin.btn.delete_confirm", lang),
        callback_data=AdmCB(action=action, arg=arg),
    )
    builder.button(
        text=t("admin.btn.cancel", lang),
        callback_data=AdmCB(action=back_action, arg=arg),
    )
    builder.adjust(1)
    return builder.as_markup()


def barber_picker_kb(
    barbers: Sequence[Barber],
    action: str,
    lang: str,
    *,
    back: str = "menu",
    with_global: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for barber in barbers:
        builder.button(text=barber.name, callback_data=AdmCB(action=action, arg=str(barber.id)))
    if with_global:
        # «Весь филиал», а не «весь барбершоп»: с Phase 3 barber_id=NULL в
        # ScheduleException означает branch-wide, а не tenant-wide.
        builder.button(
            text=t("admin.schedule.whole_branch", lang),
            callback_data=AdmCB(action=action, arg="all"),
        )
    builder.button(text=t("admin.btn.back", lang), callback_data=AdmCB(action=back))
    builder.adjust(1)
    return builder.as_markup()


def branch_picker_kb(
    branches: Sequence[Branch], action: str, lang: str, *, back: str = "menu"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for branch in branches:
        builder.button(
            text=f"📍 {branch.name}", callback_data=AdmCB(action=action, arg=str(branch.id))
        )
    builder.button(text=t("admin.btn.back", lang), callback_data=AdmCB(action=back))
    builder.adjust(1)
    return builder.as_markup()


def week_kb(barber_id: str, summary: dict[int, object], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for weekday in range(7):
        window = summary.get(weekday)
        label = (
            f"{weekday_full(weekday, lang)}: {t('admin.schedule.day_off', lang)}"
            if window is None
            else f"{weekday_full(weekday, lang)}: "
            f"{format_time(window.start)}-{format_time(window.end)}"  # type: ignore[attr-defined]
        )
        builder.button(text=label, callback_data=AdmDayCB(barber=barber_id, weekday=weekday))
    builder.button(text=t("admin.btn.back", lang), callback_data=AdmCB(action="schedule"))
    builder.adjust(1)
    return builder.as_markup()


def weekday_actions_kb(barber_id: str, weekday: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("admin.schedule.set_hours", lang),
        callback_data=AdmCB(action="sch_set", arg=f"{barber_id}|{weekday}"),
    )
    builder.button(
        text=t("admin.schedule.make_day_off", lang),
        callback_data=AdmCB(action="sch_off", arg=f"{barber_id}|{weekday}"),
    )
    builder.button(
        text=t("admin.btn.back", lang),
        callback_data=AdmCB(action="sch_barber", arg=barber_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def exceptions_kb(exceptions: Sequence[ScheduleException], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for exception in exceptions:
        scope = "🏠" if exception.is_global else "👨‍💈"
        kind = (
            t("admin.schedule.day_off", lang)
            if exception.is_day_off
            else t("admin.exceptions.special_hours", lang)
        )
        builder.button(
            text=f"{scope} {exception.exception_date.strftime('%d.%m.%Y')} · {kind}",
            callback_data=AdmCB(action="exc_del", arg=str(exception.id)),
        )
    builder.button(text=t("admin.exceptions.add", lang), callback_data=AdmCB(action="exc_add"))
    builder.button(text=t("admin.btn.back", lang), callback_data=AdmCB(action="menu"))
    builder.adjust(1)
    return builder.as_markup()


def admin_appointments_kb(
    appointments: Sequence[Appointment], page: int, has_next: bool, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for appointment in appointments:
        local = to_local(appointment.starts_at, appointment.branch.tz)
        builder.button(
            text=(
                f"{local.strftime('%d.%m %H:%M')} · {appointment.service.name}"
                f" · {appointment.barber.name}"
            ),
            callback_data=AdmCB(action="appt", arg=str(appointment.id)),
        )
    builder.adjust(1)
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=AdmCB(action="appts", arg=str(page - 1)).pack()
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="➡️", callback_data=AdmCB(action="appts", arg=str(page + 1)).pack()
            )
        )
    if navigation:
        builder.row(*navigation)
    builder.row(
        InlineKeyboardButton(
            text=t("admin.appointments.cancel_day", lang),
            callback_data=AdmCB(action="bcx_days").pack(),
        )
    )
    builder.row(_back(lang, "menu"))
    return builder.as_markup()


def bulk_cancel_days_kb(
    branch_id: str, days: list[tuple[date, int]], lang: str
) -> InlineKeyboardMarkup:
    """branch_id встроен в каждый callback (не в FSM state): confirm/execute
    ниже по цепочке повторно проверяют именно этот филиал, а не то, что
    сейчас лежит в изменяемом состоянии — см. Phase 9A §H-4 (защита от
    replay confirm-кнопки после переключения филиала)."""
    builder = InlineKeyboardBuilder()
    for day, count in days:
        builder.button(
            text=t("admin.bulk_cancel.day_row", lang, date=day.strftime("%d.%m.%Y"), count=count),
            callback_data=AdmCB(action="bcx_conf", arg=f"{branch_id}|{day.isoformat()}"),
        )
    builder.button(text=t("admin.btn.back", lang), callback_data=AdmCB(action="bcx_days"))
    builder.adjust(1)
    return builder.as_markup()


def confirm_bulk_cancel_kb(
    branch_id: str, day_iso: str, count: int, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    arg = f"{branch_id}|{day_iso}"
    builder.button(
        text=t("admin.bulk_cancel.confirm", lang, count=count),
        callback_data=AdmCB(action="bcx_ok", arg=arg),
    )
    builder.button(
        text=t("admin.btn.back", lang),
        callback_data=AdmCB(action="bcx_branch", arg=branch_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_appointment_kb(appointment_id: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("admin.appointment.reschedule", lang),
        callback_data=AdmCB(action="appt_move", arg=appointment_id),
    )
    builder.button(
        text=t("admin.appointment.cancel", lang),
        callback_data=AdmCB(action="appt_cancel", arg=appointment_id),
    )
    builder.button(
        text=t("admin.appointment.no_show", lang),
        callback_data=AdmCB(action="appt_noshow", arg=appointment_id),
    )
    builder.button(
        text=t("admin.appointment.back", lang), callback_data=AdmCB(action="appts", arg="0")
    )
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def clients_kb(page: int, has_next: bool, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=AdmCB(action="clients", arg=str(page - 1)).pack()
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="➡️", callback_data=AdmCB(action="clients", arg=str(page + 1)).pack()
            )
        )
    if navigation:
        builder.row(*navigation)
    builder.row(_back(lang, "menu"))
    return builder.as_markup()


def export_periods_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("admin.export.7d", lang),
        callback_data=AdmCB(action="export_do", arg="7"),
    )
    builder.button(
        text=t("admin.export.30d", lang),
        callback_data=AdmCB(action="export_do", arg="30"),
    )
    builder.button(
        text=t("admin.export.90d", lang),
        callback_data=AdmCB(action="export_do", arg="90"),
    )
    builder.button(
        text=t("admin.export.all", lang),
        callback_data=AdmCB(action="export_do", arg="all"),
    )
    builder.button(text=t("admin.btn.back", lang), callback_data=AdmCB(action="menu"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def back_to_admin_kb(lang: str, action: str = "menu", arg: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_back(lang, action, arg))
    return builder.as_markup()


def settings_kb(lang: str) -> InlineKeyboardMarkup:
    """Слаг и статус — read-only в этом экране (см. Phase 9C §Tenant
    Settings): для них здесь нет кнопки редактирования."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("admin.btn.name", lang), callback_data=AdmCB(action="tset_name"))
    builder.button(text=t("admin.settings.timezone", lang), callback_data=AdmCB(action="tset_tz"))
    builder.button(
        text=t("admin.settings.currency", lang),
        callback_data=AdmCB(action="tset_currency"),
    )
    builder.button(text=t("admin.settings.language", lang), callback_data=AdmCB(action="tset_lang"))
    builder.adjust(1)
    builder.row(_back(lang, "menu"))
    return builder.as_markup()


def confirm_settings_change_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("admin.btn.confirm", lang), callback_data=AdmCB(action="tset_confirm"))
    builder.button(text=t("admin.btn.cancel", lang), callback_data=AdmCB(action="settings"))
    builder.adjust(1)
    return builder.as_markup()


def _language_picker_kb(
    *, current: str | None, set_action: str, back_to: str, lang: str
) -> InlineKeyboardMarkup:
    """Общий Previous/Next-подобный переиспользуемый билдер (Phase 9E §22:
    "один канонический резолвер/механизм, а не разрозненная логика") — один
    и тот же список кнопок для выбора тенант-дефолта (§10) и персонального
    языка сотрудника (§11), различается только куда пишется результат и
    кнопка "назад". Пункты списка (LANGUAGE_NAMES) намеренно НЕ переводятся —
    "Română"/"English" называют сам язык-цель, а не текущий интерфейс."""
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGE_NAMES.items():
        mark = "✅ " if code == current else ""
        builder.button(text=f"{mark}{name}", callback_data=AdmCB(action=set_action, arg=code))
    builder.adjust(1)
    builder.row(_back(lang, back_to))
    return builder.as_markup()


def tenant_language_picker_kb(current: str, lang: str) -> InlineKeyboardMarkup:
    return _language_picker_kb(
        current=current, set_action="tset_lang_set", back_to="settings", lang=lang
    )


def staff_language_picker_kb(current: str | None, lang: str) -> InlineKeyboardMarkup:
    return _language_picker_kb(
        current=current, set_action="my_lang_set", back_to="menu", lang=lang
    )
