"""Настройки арендатора: имя/часовой пояс/валюта (Phase 9C).

Не проверяет права вызывающего — как StaffService/TenantManagementService,
это ответственность вызывающего кода (AuthorizationService.require(...,
MANAGE_SETTINGS) до вызова). slug и status намеренно не редактируются здесь:
- slug нигде не используется для лукапа/deep-link'ов сегодня (grep
  подтверждает: только отображение и проверка уникальности при создании), но
  сделать его редактируемым без явной необходимости — риск на будущее,
  которого сейчас нет смысла на себя брать; остаётся read-only.
- status меняется только через TenantOnboardingService (валидация
  готовности) и платформенный control plane (docs/PLATFORM_CONTROL_PLANE.md)
  — этот сервис не становится вторым lifecycle API.

Tenant.timezone/currency — это ДЕФОЛТ для будущих филиалов/онбординга, а не
authoritative значение для операционной бизнес-логики (та всегда читает
Branch.timezone/currency, см. Phase 9B §H-3) — эти методы никогда не трогают
существующие строки Branch."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLogEntry, Tenant
from app.database.repositories import TenantRepository

_AUDIT_ACTION = "tenant.settings_updated"


class TenantSettingsError(Exception):
    """Аналог AuthorizationError/BillingError: несёт ключ, а не готовый текст."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


class TenantSettingsService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.tenants = TenantRepository(session)

    async def get(self) -> Tenant | None:
        return await self.tenants.get(self.tenant_id)

    async def update_name(self, *, name: str, actor_telegram_id: int) -> Tenant:
        return await self._update_field(
            field="name", new_value=name, actor_telegram_id=actor_telegram_id
        )

    async def update_timezone(self, *, timezone: str, actor_telegram_id: int) -> Tenant:
        """Меняет только Tenant.timezone (дефолт для будущих филиалов) —
        существующие Branch.timezone не затрагиваются: Branch хранит своё
        значение независимо, скопированное при создании (см.
        BranchRepository.create)."""
        return await self._update_field(
            field="timezone", new_value=timezone, actor_telegram_id=actor_telegram_id
        )

    async def update_currency(self, *, currency: str, actor_telegram_id: int) -> Tenant:
        """См. update_timezone — то же самое для валюты: только дефолт для
        будущих филиалов, существующие Branch.currency не меняются."""
        return await self._update_field(
            field="currency", new_value=currency, actor_telegram_id=actor_telegram_id
        )

    async def update_default_language(
        self, *, language: str, actor_telegram_id: int
    ) -> Tenant:
        """Дефолт языка для будущих сотрудников/клиентов (Phase 9E) — не
        трогает уже сохранённые StaffMember.language / User.language_code,
        ровно как update_timezone/update_currency не трогают Branch."""
        return await self._update_field(
            field="default_language", new_value=language, actor_telegram_id=actor_telegram_id
        )

    async def _update_field(self, *, field: str, new_value: str, actor_telegram_id: int) -> Tenant:
        tenant = await self.tenants.get(self.tenant_id)
        if tenant is None:
            raise TenantSettingsError("settings.tenant_not_found")
        old_value = getattr(tenant, field)
        setattr(tenant, field, new_value)
        self.session.add(
            AuditLogEntry(
                tenant_id=self.tenant_id,
                actor_telegram_id=actor_telegram_id,
                action=_AUDIT_ACTION,
                details={"field": field, "old": old_value, "new": new_value},
            )
        )
        await self.session.commit()
        return tenant
