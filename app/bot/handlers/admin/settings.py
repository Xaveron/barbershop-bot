"""Админ: настройки арендатора (Phase 9C, +default_language в Phase 9E,
локализация в Phase 9F) — имя, часовой пояс, валюта, язык по умолчанию.

Гейтится Permission.MANAGE_SETTINGS на уровне роутера (не MANAGE_TENANT —
та остаётся правом жизненного цикла онбординга/активации, см.
app/bot/handlers/onboarding.py и docs/PLATFORM_CONTROL_PLANE.md; здесь про
профиль уже существующего арендатора). Слаг и статус — read-only: слаг нигде
не используется для лукапа/deep-link'ов сегодня (см.
app/services/tenant_settings.py), но не редактируется без явной
необходимости; статус меняется только через TenantOnboardingService/
платформенный control plane — этот экран не становится вторым lifecycle
API. Язык по умолчанию — только дефолт для будущих сотрудников/клиентов
(см. app/services/locale.py); уже сохранённые StaffMember.language/
User.language_code этим экраном не трогаются. Личный язык КОНКРЕТНОГО
сотрудника — отдельный самостоятельный флоу без MANAGE_SETTINGS, см.
app/bot/handlers/admin/language.py (Phase 9E §11).

Phase 9F: весь текст этого экрана рендерится на staff_lang (язык
ДЕЙСТВУЮЩЕГО сотрудника — StaffMember.language -> Tenant.default_language ->
FALLBACK, см. app/services/locale.py), а НЕ на data["lang"] (тот — язык
клиента) и НЕ на settings.default_language (процесс-wide)."""

from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import LANGUAGE_NAMES, LANGUAGES, t
from app.bot.keyboards.admin import (
    confirm_settings_change_kb,
    settings_kb,
    tenant_language_picker_kb,
)
from app.bot.keyboards.callbacks import AdmCB
from app.bot.middlewares.permissions import RequirePermission
from app.bot.states import AdminSettingsSG
from app.bot.utils import alert, edit_message
from app.database.models import Permission, Tenant
from app.database.repositories import TenantRepository
from app.services.tenant_settings import TenantSettingsService
from app.utils.text import esc
from app.utils.validators import (
    ValidationError,
    validate_currency,
    validate_name,
    validate_timezone,
)

logger = logging.getLogger(__name__)
router = Router(name="admin-settings")
router.message.filter(RequirePermission(Permission.MANAGE_SETTINGS))
router.callback_query.filter(RequirePermission(Permission.MANAGE_SETTINGS))

_FIELD_LABEL_KEYS: dict[str, str] = {
    "name": "admin.settings.field_name",
    "timezone": "admin.settings.field_timezone",
    "currency": "admin.settings.field_currency",
    "default_language": "admin.settings.field_language",
}
_FIELD_VALIDATORS = {
    "name": validate_name,
    "timezone": validate_timezone,
    "currency": validate_currency,
}
_FIELD_ACTIONS = {
    "tset_name": "name",
    "tset_tz": "timezone",
    "tset_currency": "currency",
}
_FIELD_PROMPT_KEYS: dict[str, str] = {
    "name": "admin.settings.prompt_name",
    "timezone": "admin.settings.prompt_timezone",
    "currency": "admin.settings.prompt_currency",
}


def _settings_text(tenant: Tenant, lang: str) -> str:
    language_label = LANGUAGE_NAMES.get(tenant.default_language, tenant.default_language)
    lines = [
        t("admin.settings.title", lang),
        "",
        t("admin.settings.line_name", lang, value=esc(tenant.name)),
        t("admin.settings.line_slug", lang, slug=esc(tenant.slug)),
        t("admin.settings.line_timezone", lang, value=esc(tenant.timezone)),
        t("admin.settings.line_currency", lang, value=esc(tenant.currency)),
        t("admin.settings.line_language", lang, value=esc(language_label)),
        t("admin.settings.line_status", lang, value=esc(tenant.status.value)),
        "",
        t("admin.settings.defaults_notice", lang),
    ]
    return "\n".join(lines)


@router.callback_query(AdmCB.filter(F.action == "settings"))
async def show_settings(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    await state.clear()
    tenant = await TenantRepository(session).get(tenant_id)
    if tenant is None:
        await alert(callback, t("admin.settings.not_found", staff_lang))
        return
    await edit_message(callback, _settings_text(tenant, staff_lang), settings_kb(staff_lang))
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "tset_lang"))
async def start_edit_language(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    """Выбор кнопкой, а не свободным текстом (Phase 9E §10: "Supported
    choices: Русский/Română/English") — тот же экран подтверждения
    (AdminSettingsSG.confirm/tset_confirm), что и у остальных полей."""
    await state.clear()
    tenant = await TenantRepository(session).get(tenant_id)
    current = tenant.default_language if tenant is not None else None
    await edit_message(
        callback,
        t("admin.settings.pick_language_prompt", staff_lang),
        tenant_language_picker_kb(current or "", staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "tset_lang_set"))
async def pick_language(
    callback: CallbackQuery, callback_data: AdmCB, state: FSMContext, staff_lang: str
) -> None:
    code = callback_data.arg
    if code not in LANGUAGES:
        await alert(callback, t("admin.settings.unknown_language", staff_lang))
        return
    await state.update_data(field="default_language", pending_value=code)
    await state.set_state(AdminSettingsSG.confirm)
    await edit_message(
        callback,
        t(
            "admin.settings.confirm_change",
            staff_lang,
            field=t("admin.settings.field_language", staff_lang),
            value=esc(LANGUAGE_NAMES[code]),
        ),
        confirm_settings_change_kb(staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action.in_(set(_FIELD_ACTIONS))))
async def start_edit_field(
    callback: CallbackQuery, callback_data: AdmCB, state: FSMContext, staff_lang: str
) -> None:
    field = _FIELD_ACTIONS[callback_data.action]
    await state.set_state(AdminSettingsSG.value)
    await state.update_data(field=field)
    prompt = t(_FIELD_PROMPT_KEYS[field], staff_lang)
    cancel_hint = t("admin.settings.cancel_hint", staff_lang)
    await edit_message(
        callback,
        f"{prompt}\n\n{cancel_hint}",
        settings_kb(staff_lang),
    )
    await callback.answer()


@router.message(AdminSettingsSG.value)
async def receive_new_value(message: Message, state: FSMContext, staff_lang: str) -> None:
    data = await state.get_data()
    field = data.get("field")
    validator = _FIELD_VALIDATORS.get(field) if field else None
    if validator is None:
        await state.clear()
        await message.answer(t("admin.errors.session_expired", staff_lang))
        return
    try:
        value = validator(message.text or "")
    except ValidationError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(pending_value=str(value))
    await state.set_state(AdminSettingsSG.confirm)
    await message.answer(
        t(
            "admin.settings.confirm_change",
            staff_lang,
            field=t(_FIELD_LABEL_KEYS[field], staff_lang),
            value=esc(str(value)),
        ),
        reply_markup=confirm_settings_change_kb(staff_lang),
    )


@router.callback_query(AdminSettingsSG.confirm, AdmCB.filter(F.action == "tset_confirm"))
async def confirm_edit(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff_lang: str,
) -> None:
    data = await state.get_data()
    field = data.get("field")
    pending_value = data.get("pending_value")
    await state.clear()
    if field is None or pending_value is None or callback.from_user is None:
        await alert(callback, t("admin.errors.session_expired", staff_lang))
        return

    service = TenantSettingsService(session, tenant_id)
    actor_id = callback.from_user.id
    if field == "name":
        tenant = await service.update_name(name=pending_value, actor_telegram_id=actor_id)
    elif field == "timezone":
        tenant = await service.update_timezone(
            timezone=pending_value, actor_telegram_id=actor_id
        )
    elif field == "currency":
        tenant = await service.update_currency(
            currency=pending_value, actor_telegram_id=actor_id
        )
    else:
        tenant = await service.update_default_language(
            language=pending_value, actor_telegram_id=actor_id
        )

    await edit_message(callback, _settings_text(tenant, staff_lang), settings_kb(staff_lang))
    await callback.answer(t("admin.errors.saved", staff_lang))
