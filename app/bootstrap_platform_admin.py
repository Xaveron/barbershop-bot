"""Разово переносит ADMIN_ID в DB-backed PlatformOperator:

    python -m app.bootstrap_platform_admin

Phase 8: до этой команды ADMIN_ID временно действует как bootstrap-сигнал
(см. app/services/platform_authorization.py) — самозавершающееся окно, пока
platform_operators пуста. После неё нормальная авторизация всегда идёт через
таблицу, а ADMIN_ID для авторизации больше не используется.

Идемпотентен: уже существующий telegram_user_id пропускается. Создаёт по
одной строке на КАЖДЫЙ id из ADMIN_ID (не только первый) — это сохраняет
сегодняшний фактический уровень доступа, а не сужает его молча. Никаких
секретов здесь нет и печатать нечего, кроме telegram_id."""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import build_engine, build_session_factory, wait_for_database
from app.database.repositories import PlatformOperatorRepository
from app.services.platform_authorization import PlatformAuthorizationService
from app.utils.logging import mask_secrets, setup_logging

logger = logging.getLogger(__name__)


async def bootstrap_platform_admin() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.admin_ids:
        logger.error("ADMIN_ID не задан — нечего переносить")
        return 1

    try:
        engine = build_engine(settings.database_url, echo=settings.sql_echo)
        session_factory = build_session_factory(engine)
        await wait_for_database(engine)
    except Exception as exc:
        logger.error("Не удалось подключиться к базе данных: %s", mask_secrets(str(exc)))
        return 1

    try:
        async with session_factory() as session:
            repository = PlatformOperatorRepository(session)
            auth = PlatformAuthorizationService(session, settings)
            created = 0
            for telegram_id in settings.admin_ids:
                if await repository.get_by_telegram_id(telegram_id) is not None:
                    logger.info("telegram_user_id=%s уже PlatformOperator — пропуск", telegram_id)
                    continue
                # actor = сам себя: это и есть точка, откуда операторы
                # впервые появляются, self-attribution осмыслен.
                await auth.create_operator(
                    telegram_user_id=telegram_id, actor_telegram_id=telegram_id
                )
                created += 1
                logger.info("Создан PlatformOperator telegram_user_id=%s", telegram_id)
        logger.info("Готово: создано %s, остальные уже существовали", created)
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(bootstrap_platform_admin()))


if __name__ == "__main__":
    main()
