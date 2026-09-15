from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import TelegramBotIdentity
from app.database.repositories.base import BaseRepository


class TelegramBotIdentityRepository(BaseRepository):
    """Не tenant-scoped намеренно: её главная задача — найти арендатора ПО
    bot_id, когда арендатор ещё не известен (см. docs/BOT_IDENTITY_ARCHITECTURE.md)."""

    async def get_by_bot_id(self, telegram_bot_id: int) -> TelegramBotIdentity | None:
        """Возвращает строку независимо от is_active — вызывающий сам решает,
        как отличить «неизвестный bot» от «известный, но отключённый»."""
        stmt = select(TelegramBotIdentity).where(
            TelegramBotIdentity.telegram_bot_id == telegram_bot_id
        )
        return await self.session.scalar(stmt)

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[TelegramBotIdentity]:
        stmt = (
            select(TelegramBotIdentity)
            .where(TelegramBotIdentity.tenant_id == tenant_id)
            .order_by(TelegramBotIdentity.created_at)
        )
        return list(await self.session.scalars(stmt))

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        telegram_bot_id: int,
        username: str | None,
        is_active: bool = True,
    ) -> TelegramBotIdentity:
        identity = TelegramBotIdentity(
            tenant_id=tenant_id,
            telegram_bot_id=telegram_bot_id,
            username=username,
            is_active=is_active,
        )
        self.session.add(identity)
        await self.session.flush()
        return identity
