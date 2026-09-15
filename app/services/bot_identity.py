"""Bot identity -> tenant resolution (Phase 7).

Заменяет process-global default tenant: вместо одного tenant_id, разрешённого
один раз при старте процесса (app/database/tenants.py::resolve_default_tenant_id),
каждый апдейт разрешает своего арендатора через Bot.id (см.
app/bot/middlewares/bot_identity.py, docs/BOT_IDENTITY_ARCHITECTURE.md).

Никакого process-wide кэша и никакого fallback на "первого арендатора" —
неизвестный/отключённый bot должен провалиться явно, а не тихо получить
чужого или дефолтного арендатора."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TelegramBotIdentity
from app.database.repositories import TelegramBotIdentityRepository


class BotIdentityResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.identities = TelegramBotIdentityRepository(session)

    async def resolve(self, telegram_bot_id: int) -> TelegramBotIdentity | None:
        """Возвращает строку identity как есть (в т.ч. is_active=False) —
        вызывающий сам решает, как трактовать «неизвестный» и «отключённый»
        bot (обычно по-разному логируются, см. BotIdentityMiddleware)."""
        return await self.identities.get_by_bot_id(telegram_bot_id)


class BotAlreadyAssignedError(Exception):
    """Bot уже привязан к другому арендатору — переподключение отклоняется
    явно, а не молча (Phase 8, см. docs/PLATFORM_CONTROL_PLANE.md §10)."""

    def __init__(self, telegram_bot_id: int, current_tenant_id: uuid.UUID) -> None:
        super().__init__(
            f"bot_id={telegram_bot_id} уже привязан к арендатору {current_tenant_id}"
        )
        self.telegram_bot_id = telegram_bot_id
        self.current_tenant_id = current_tenant_id


class BotProvisioningService:
    """Единственная реализация «привязать/отключить bot» — используется и
    app/register_bot.py (CLI), и TenantManagementService (платформенный UI).
    Не создавать вторую (Phase 8 §10)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identities = TelegramBotIdentityRepository(session)

    async def attach(
        self, *, tenant_id: uuid.UUID, telegram_bot_id: int, username: str | None
    ) -> tuple[TelegramBotIdentity, bool]:
        """Возвращает (identity, created). created=False — идемпотентный
        повторный вызов с тем же (tenant_id, telegram_bot_id)."""
        existing = await self.identities.get_by_bot_id(telegram_bot_id)
        if existing is not None:
            if existing.tenant_id == tenant_id:
                return existing, False
            raise BotAlreadyAssignedError(telegram_bot_id, existing.tenant_id)
        identity = await self.identities.create(
            tenant_id=tenant_id, telegram_bot_id=telegram_bot_id, username=username
        )
        return identity, True

    async def deactivate(self, telegram_bot_id: int) -> TelegramBotIdentity | None:
        return await self._set_active(telegram_bot_id, False)

    async def activate(self, telegram_bot_id: int) -> TelegramBotIdentity | None:
        """Симметрично deactivate — безопасно без токена: identity уже
        существует, меняется только is_active."""
        return await self._set_active(telegram_bot_id, True)

    async def _set_active(
        self, telegram_bot_id: int, is_active: bool
    ) -> TelegramBotIdentity | None:
        identity = await self.identities.get_by_bot_id(telegram_bot_id)
        if identity is None:
            return None
        identity.is_active = is_active
        await self.session.flush()
        return identity
