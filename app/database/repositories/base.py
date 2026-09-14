from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Общий базовый репозиторий: хранит сессию, не управляет транзакцией.

    Коммит выполняет вызывающий сервис — так одна бизнес-операция
    остаётся одной транзакцией.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class TenantScopedRepository(BaseRepository):
    """Базовый репозиторий для таблиц, принадлежащих арендатору.

    tenant_id обязателен в конструкторе — как и session, его нельзя забыть
    на одном из call site'ов. Каждый конкретный метод обязан явно добавить
    `Model.tenant_id == self.tenant_id` в WHERE (здесь нет автоматического
    перехвата запросов — сохраняем стиль хендрайтинга запросов этого слоя).
    """

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session)
        self.tenant_id = tenant_id
