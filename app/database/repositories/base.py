from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Общий базовый репозиторий: хранит сессию, не управляет транзакцией.

    Коммит выполняет вызывающий сервис — так одна бизнес-операция
    остаётся одной транзакцией.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
