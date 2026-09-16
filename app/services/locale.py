"""Единый резолвер языка (Phase 9E) — единственное место, где сходятся
StaffMember.language / User.language_code / Tenant.default_language /
FALLBACK_LANGUAGE. Ни один вызывающий код не должен собирать эту цепочку
самостоятельно (см. §22 требования фазы: "один канонический резолвер, а не
разрозненная fallback-логика").

Правило для обеих цепочек одинаковое:

    явное личное предпочтение -> Tenant.default_language -> FALLBACK_LANGUAGE

Telegram language_code участвует ТОЛЬКО в инициализации нового User (см.
initial_customer_language) — никогда в резолюции уже сохранённого предпочтения:
once a stored personal language exists, живой язык клиента Telegram больше не
может его молча заменить (UserRepository.get_or_create уже гарантирует это на
уровне записи — language_code пишется только при создании строки)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import FALLBACK_LANGUAGE, normalize_language
from app.database.models import StaffMember, User
from app.database.repositories import TenantRepository


async def get_tenant_default_language(session: AsyncSession, tenant_id: uuid.UUID | None) -> str:
    """Единая точка чтения Tenant.default_language с безопасным fallback —
    используется там, где ещё не резолвлен per-update tenant_default_language
    (см. app/bot/middlewares/bot_identity.py, которая делает это один раз на
    апдейт и кладёт результат в data["tenant_default_language"])."""
    if tenant_id is None:
        return FALLBACK_LANGUAGE
    tenant = await TenantRepository(session).get(tenant_id)
    return normalize_language(tenant.default_language if tenant else None, FALLBACK_LANGUAGE)


def resolve_staff_locale(staff: StaffMember | None, tenant_default_language: str) -> str:
    """StaffMember.language (явное) -> tenant_default_language -> FALLBACK."""
    return normalize_language(
        staff.language if staff is not None else None, default=tenant_default_language
    )


def resolve_customer_locale(user: User | None, tenant_default_language: str) -> str:
    """User.language_code (явное) -> tenant_default_language -> FALLBACK."""
    return normalize_language(
        user.language_code if user is not None else None, default=tenant_default_language
    )


def initial_customer_language(
    telegram_language_code: str | None, tenant_default_language: str
) -> str:
    """Только для СОЗДАНИЯ новой строки User (первый контакт) — телеграмный
    language_code клиента, если он поддерживается, иначе дефолт арендатора.
    Не применяется к уже существующему User (см. модульный докстринг)."""
    return normalize_language(telegram_language_code, default=tenant_default_language)
