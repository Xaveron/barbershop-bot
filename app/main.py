"""Точка входа: инициализация бота, БД, планировщика и graceful shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from app.bot.handlers import build_router
from app.bot.middlewares import (
    DatabaseMiddleware,
    PrivateChatOnlyMiddleware,
    TextLimitMiddleware,
    ThrottlingMiddleware,
    UserContextMiddleware,
)
from app.config import Settings, get_settings
from app.database import build_engine, build_session_factory, wait_for_database
from app.scheduler import build_scheduler
from app.utils.logging import setup_logging

logger = logging.getLogger(__name__)

USER_COMMANDS = (
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="help", description="Как пользоваться ботом"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
)
ADMIN_COMMANDS = (*USER_COMMANDS, BotCommand(command="admin", description="Админ-панель"))


async def setup_commands(bot: Bot, settings: Settings) -> None:
    await bot.set_my_commands(list(USER_COMMANDS), scope=BotCommandScopeDefault())
    for admin_id in settings.admin_ids:
        with contextlib.suppress(Exception):
            await bot.set_my_commands(
                list(ADMIN_COMMANDS), scope=BotCommandScopeChat(chat_id=admin_id)
            )


def _build_storage(settings: Settings) -> MemoryStorage | RedisStorage:
    if settings.redis_url:
        logger.info("FSM хранилище: Redis (%s)", settings.redis_url.split("@")[-1])
        return RedisStorage.from_url(settings.redis_url)
    logger.warning("REDIS_URL не задан — FSM в памяти (состояния теряются при перезапуске)")
    return MemoryStorage()


def build_dispatcher(settings: Settings, session_factory) -> Dispatcher:
    dispatcher = Dispatcher(storage=_build_storage(settings))
    dispatcher["settings"] = settings
    dispatcher["session_factory"] = session_factory

    # Порядок важен: только личные чаты → троттлинг → сессия БД → пользователь.
    dispatcher.update.outer_middleware(PrivateChatOnlyMiddleware(settings.default_language))
    dispatcher.update.outer_middleware(
        ThrottlingMiddleware(
            interval=settings.throttle_interval,
            burst=settings.throttle_burst,
            default_language=settings.default_language,
        )
    )
    dispatcher.update.outer_middleware(DatabaseMiddleware(session_factory))
    dispatcher.update.outer_middleware(UserContextMiddleware(settings))

    dispatcher.include_router(build_router())
    return dispatcher


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Запуск бота, часовой пояс: %s", settings.timezone)
    if not settings.admin_ids:
        logger.warning("ADMIN_ID не задан — админ-панель будет недоступна")

    engine = build_engine(settings.database_url, echo=settings.sql_echo)
    session_factory = build_session_factory(engine)
    await wait_for_database(engine)

    session = None
    if settings.telegram_api_base:
        logger.info("Используется локальный Bot API server: %s", settings.telegram_api_base)
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.telegram_api_base.rstrip("/"))
        )

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # Страховка от лимитов Telegram на длину текста — на всех исходящих запросах.
    bot.session.middleware(TextLimitMiddleware())
    dispatcher = build_dispatcher(settings, session_factory)
    scheduler = build_scheduler(bot, session_factory, settings)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            logger.error("Telegram отклонил токен. Проверьте BOT_TOKEN в .env")
            return
        except TelegramNetworkError as error:
            logger.error("Telegram API недоступен: %s", error)
            return
        logger.info("Бот запущен: @%s", me.username)
        await setup_commands(bot, settings)
        # Сбрасываем возможный вебхук, иначе long polling не получит апдейты.
        await bot.delete_webhook(drop_pending_updates=False)
        scheduler.start()

        polling = asyncio.create_task(
            dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
                handle_signals=False,
            ),
            name="polling",
        )
        stopper = asyncio.create_task(stop_event.wait(), name="stop-signal")
        done, _ = await asyncio.wait({polling, stopper}, return_when=asyncio.FIRST_COMPLETED)

        if polling in done:
            stopper.cancel()
            polling.result()
        else:
            logger.info("Получен сигнал остановки, завершаем работу...")
            with contextlib.suppress(RuntimeError):
                await dispatcher.stop_polling()
            with contextlib.suppress(asyncio.CancelledError):
                await polling
    finally:
        logger.info("Graceful shutdown...")
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await dispatcher.storage.close()
        await bot.session.close()
        await engine.dispose()
        logger.info("Остановлено")


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
