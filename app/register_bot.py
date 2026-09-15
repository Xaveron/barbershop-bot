"""Регистрирует Telegram-бота (BOT_TOKEN) за конкретным арендатором:

    python -m app.register_bot --tenant-id <uuid>

Phase 7: единственный контролируемый способ появления строки в
telegram_bot_identities — миграция 0011 намеренно не бэкфиллит её сама (см.
docs/BOT_IDENTITY_ARCHITECTURE.md). Токен ТОЛЬКО из переменной окружения
BOT_TOKEN (через Settings) — никогда как аргумент командной строки и никогда
не печатается/логируется.

Идемпотентен: повторный запуск с тем же --tenant-id для уже
зарегистрированного бота — no-op. Запуск с ДРУГИМ --tenant-id для уже
зарегистрированного бота отклоняется явной ошибкой — переподключить бота к
другому арендатору не может опечатка в аргументе.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

from aiogram import Bot
from aiogram.exceptions import TelegramUnauthorizedError

from app.config import get_settings
from app.database import build_engine, build_session_factory, wait_for_database
from app.database.repositories import TelegramBotIdentityRepository, TenantRepository
from app.utils.logging import mask_secrets, setup_logging

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id", required=True, type=uuid.UUID, help="UUID арендатора из таблицы tenants"
    )
    return parser.parse_args()


async def register_bot(tenant_id: uuid.UUID) -> int:
    settings = get_settings()
    setup_logging(settings.log_level)

    try:
        engine = build_engine(settings.database_url, echo=settings.sql_echo)
        session_factory = build_session_factory(engine)
        await wait_for_database(engine)
    except Exception as exc:
        logger.error("Не удалось подключиться к базе данных: %s", mask_secrets(str(exc)))
        return 1

    bot = Bot(token=settings.bot_token.get_secret_value())
    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            logger.error("Telegram отклонил BOT_TOKEN — проверьте значение в окружении")
            return 1

        async with session_factory() as session:
            tenant = await TenantRepository(session).get(tenant_id)
            if tenant is None:
                logger.error("Арендатор %s не найден", tenant_id)
                return 1

            repository = TelegramBotIdentityRepository(session)
            existing = await repository.get_by_bot_id(me.id)
            if existing is not None:
                if existing.tenant_id == tenant_id:
                    logger.info(
                        "bot_id=%s (@%s) уже зарегистрирован за арендатором %s — ничего не делаем",
                        me.id, me.username, tenant_id,
                    )
                    return 0
                logger.error(
                    "bot_id=%s (@%s) уже зарегистрирован за ДРУГИМ арендатором (%s) — "
                    "отказ, чтобы случайно не переподключить бота. Уберите старую "
                    "привязку вручную, если это осознанное решение.",
                    me.id, me.username, existing.tenant_id,
                )
                return 1

            await repository.create(
                tenant_id=tenant_id, telegram_bot_id=me.id, username=me.username
            )
            await session.commit()
            logger.info(
                "Зарегистрирован bot_id=%s (@%s) за арендатором %s (%s)",
                me.id, me.username, tenant_id, tenant.name,
            )
            return 0
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    args = _parse_args()
    exit_code = asyncio.run(register_bot(args.tenant_id))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
