"""Личный язык интерфейса сотрудника (Phase 9E §11).

Отдельно от app/bot/handlers/admin/settings.py: это персональное
предпочтение (StaffMember.language), а не настройка арендатора — доступно
ЛЮБОМУ активному сотруднику без Permission.MANAGE_SETTINGS (роутер не
добавляет RequirePermission поверх родительского IsStaff, см.
app/bot/handlers/admin/__init__.py). Не создаёт новое право: используется
существующая архитектура авторизации (IsStaff уже гейтит весь админ-роутер).

Меняет только StaffMember.language текущего сотрудника — никогда
Tenant.default_language, User.language_code, других сотрудников или
TelegramBotIdentity (см. app/services/locale.py)."""

from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import LANGUAGES, t
from app.bot.keyboards.admin import staff_language_picker_kb
from app.bot.keyboards.callbacks import AdmCB
from app.bot.utils import alert, edit_message
from app.database.models import StaffMember
from app.database.repositories import StaffRepository

router = Router(name="admin-language")


@router.callback_query(AdmCB.filter(F.action == "my_lang"))
async def open_my_language(
    callback: CallbackQuery, staff: StaffMember | None, staff_lang: str
) -> None:
    if staff is None:
        # Платформенный оператор без собственной строки StaffMember в этом
        # арендаторе — сохранять личный язык здесь некуда (см. Phase 9E §17:
        # PlatformOperator.language не добавляется в этой фазе).
        await alert(callback, t("admin.language.staff_only", staff_lang))
        return
    # Галочка — на РЕЗОЛВЛЕННОМ языке (staff_lang, учитывает наследование
    # Tenant.default_language при NULL), а не на "сыром" staff.language,
    # который у большинства сотрудников NULL (см. app/services/locale.py).
    await edit_message(
        callback,
        t("admin.language.pick_prompt", staff_lang),
        staff_language_picker_kb(staff_lang, staff_lang),
    )
    await callback.answer()


@router.callback_query(AdmCB.filter(F.action == "my_lang_set"))
async def set_my_language(
    callback: CallbackQuery,
    callback_data: AdmCB,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    staff: StaffMember | None,
    staff_lang: str,
) -> None:
    if staff is None:
        await alert(callback, t("admin.language.staff_only", staff_lang))
        return
    code = callback_data.arg
    if code not in LANGUAGES:
        await alert(callback, t("admin.language.unknown_language", staff_lang))
        return
    # tenant_id из DI (bot identity), а не из callback — staff тоже уже
    # резолвлен StaffContextMiddleware в рамках этого tenant_id, так что
    # запись всегда попадает в правильного сотрудника правильного
    # арендатора (см. Phase 9E §18).
    await StaffRepository(session, tenant_id).set_language(staff, code)
    await session.commit()
    # После сохранения РЕЗОЛВЛЕННЫЙ язык этого сотрудника — только что
    # выбранный code (явное значение всегда побеждает), поэтому текст
    # экрана рендерим уже на нём, а не на устаревшем staff_lang из DI этого
    # апдейта (staff_lang был резолвлен ДО записи).
    await edit_message(
        callback,
        t("admin.language.saved_notice", code),
        staff_language_picker_kb(code, code),
    )
    await callback.answer(t("admin.errors.saved", code))
