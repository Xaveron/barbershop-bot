"""Bot identity -> tenant resolution (Phase 7).

Заменяет process-global default tenant: вместо одного tenant_id, разрешённого
один раз при старте процесса (app/database/tenants.py::resolve_default_tenant_id),
каждый апдейт разрешает своего арендатора через Bot.id (см.
app/bot/middlewares/bot_identity.py, docs/BOT_IDENTITY_ARCHITECTURE.md).

Никакого process-wide кэша и никакого fallback на "первого арендатора" —
неизвестный/отключённый bot должен провалиться явно, а не тихо получить
чужого или дефолтного арендатора."""

from __future__ import annotations

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
