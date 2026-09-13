"""Фильтр доступа к админ-панели."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.config import Settings


class IsAdmin(BaseFilter):
    """Пропускает событие только от Telegram ID, перечисленных в ADMIN_ID.

    Фильтр «молчаливый»: он не отвечает пользователю и не пишет в лог, иначе
    каждое сообщение обычного клиента порождало бы отказ и запись в журнале —
    фильтр проверяется на каждом апдейте. Ответ на реальную попытку открыть
    админ-раздел и запись в лог даёт fallback-роутер.
    """

    async def __call__(self, event: TelegramObject, settings: Settings | None = None) -> bool:
        if settings is None:  # pragma: no cover - защитная ветка
            return False
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        return settings.is_admin(user.id)
