"""Создание async-движка и фабрики сессий SQLAlchemy."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.utils.logging import mask_secrets

logger = logging.getLogger(__name__)


# Серверные таймауты: зависшая транзакция не должна держать соединение из пула
# и блокировать advisory-lock барбера для остальных клиентов.
SERVER_SETTINGS = {
    "application_name": "barbershop_bot",
    "statement_timeout": "15000",
    "idle_in_transaction_session_timeout": "30000",
    # Планировщик и все запросы работают в UTC независимо от настроек сервера.
    "timezone": "UTC",
}


def build_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(
        database_url,
        echo=echo,
        # Параметры запросов (могут содержать ПДн) никогда не попадают в лог/исключения,
        # даже если echo=True — включённый SQL_ECHO должен показывать только сами запросы.
        hide_parameters=True,
        pool_size=10,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=10,
        connect_args={
            "timeout": 10,
            "command_timeout": 30,
            "server_settings": SERVER_SETTINGS,
        },
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def wait_for_database(engine: AsyncEngine, *, attempts: int = 15, delay: float = 2.0) -> None:
    """Ждём готовности PostgreSQL (важно при перезапуске compose)."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            logger.info("Соединение с базой данных установлено")
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "База недоступна (попытка %s/%s): %s", attempt, attempts, mask_secrets(str(exc))
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"Не удалось подключиться к базе данных: {mask_secrets(str(last_error))}")
