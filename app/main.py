"""Точка входа: инициализация ботов, БД, планировщика и graceful shutdown.

Phase 7: процесс может обслуживать несколько Telegram-ботов одновременно —
каждый bot принадлежит своему арендатору (app/database/models/bot_identity.py),
разрешаемому заново на каждый апдейт (app/bot/middlewares/bot_identity.py), а
не один раз при старте процесса."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from app.bot.handlers import build_router
from app.bot.middlewares import (
    BotIdentityMiddleware,
    DatabaseMiddleware,
    PrivateChatOnlyMiddleware,
    StaffContextMiddleware,
    TextLimitMiddleware,
    ThrottlingMiddleware,
    UserContextMiddleware,
)
from app.config import Settings, get_settings
from app.database import build_engine, build_session_factory, wait_for_database
from app.scheduler import build_scheduler
from app.services.bot_identity import BotIdentityResolver
from app.utils.logging import mask_secrets, setup_logging

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
    """Больше не принимает tenant_id: арендатор разрешается per-update
    BotIdentityMiddleware, а не один раз здесь (см. модуль-докстринг)."""
    dispatcher = Dispatcher(storage=_build_storage(settings))
    dispatcher["settings"] = settings
    dispatcher["session_factory"] = session_factory

    # Порядок важен: троттлинг → только личные чаты → сессия БД → bot identity
    # (нужна data["session"] от DatabaseMiddleware) → пользователь (уже читает
    # data["tenant_id"], который выставляет BotIdentityMiddleware) → персонал.
    dispatcher.update.outer_middleware(
        ThrottlingMiddleware(
            interval=settings.throttle_interval,
            burst=settings.throttle_burst,
            default_language=settings.default_language,
        )
    )
    dispatcher.update.outer_middleware(PrivateChatOnlyMiddleware(settings.default_language))
    dispatcher.update.outer_middleware(DatabaseMiddleware(session_factory))
    dispatcher.update.outer_middleware(BotIdentityMiddleware())
    dispatcher.update.outer_middleware(UserContextMiddleware(settings))
    dispatcher.update.outer_middleware(StaffContextMiddleware(settings))

    dispatcher.include_router(build_router())
    return dispatcher


def _build_bot(token: str, session: BaseSession | None) -> Bot:
    bot = Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # Страховка от лимитов Telegram на длину текста — на всех исходящих запросах.
    bot.session.middleware(TextLimitMiddleware())
    return bot


async def _validate_bots(bots: list[Bot], settings: Settings) -> list[Bot]:
    """Проверяет каждый bot независимо: невалидный токен исключает только
    этот bot (его арендатор останется без обслуживания), а не весь процесс —
    один сломанный bot не должен положить остальных арендаторов."""
    validated: list[Bot] = []
    for bot in bots:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            logger.error(
                "Telegram отклонил токен bot_id=%s. Проверьте BOT_TOKEN/BOT_TOKENS", bot.id
            )
            continue
        except TelegramNetworkError as error:
            logger.error("Telegram API недоступен для bot_id=%s: %s", bot.id, error)
            continue
        logger.info("Бот запущен: @%s (id=%s)", me.username, bot.id)
        await setup_commands(bot, settings)
        validated.append(bot)
    return validated


async def _resolve_bots_by_tenant(
    bots: list[Bot], session_factory
) -> dict[uuid.UUID, Bot]:
    """Один bot на арендатора для планировщика: если у арендатора несколько
    активных identity, побеждает та, что зарегистрирована раньше остальных —
    не влияет на ответные сообщения (они всегда идут через тот bot, которому
    реально написал клиент), только на то, через какой bot планировщик шлёт
    напоминания этому арендатору (см. docs/BOT_IDENTITY_ARCHITECTURE.md)."""
    earliest: dict[uuid.UUID, tuple] = {}
    async with session_factory() as session:
        resolver = BotIdentityResolver(session)
        for bot in bots:
            identity = await resolver.resolve(bot.id)
            if identity is None or not identity.is_active:
                logger.warning(
                    "bot_id=%s не привязан к активному арендатору — "
                    "напоминания для него не будут запланированы",
                    bot.id,
                )
                continue
            existing = earliest.get(identity.tenant_id)
            if existing is None or identity.created_at < existing[0]:
                earliest[identity.tenant_id] = (identity.created_at, bot)
    return {tenant_id: bot for tenant_id, (_created_at, bot) in earliest.items()}


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Запуск бота, часовой пояс: %s", settings.timezone)
    if not settings.admin_ids:
        logger.warning("ADMIN_ID не задан — админ-панель будет недоступна")

    try:
        engine = build_engine(settings.database_url, echo=settings.sql_echo)
        session_factory = build_session_factory(engine)
        await wait_for_database(engine)
    except Exception as exc:
        # Не даём необработанному исключению всплыть в stderr как есть: сообщение об
        # ошибке разбора DSN (например, от SQLAlchemy) может содержать пароль целиком.
        logger.error("Не удалось подключиться к базе данных: %s", mask_secrets(str(exc)))
        return

    api_session: BaseSession | None = None
    if settings.telegram_api_base:
        logger.info("Используется локальный Bot API server: %s", settings.telegram_api_base)
        api_session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.telegram_api_base.rstrip("/"))
        )

    bots = [_build_bot(token, api_session) for token in settings.bot_tokens_all]
    dispatcher = build_dispatcher(settings, session_factory)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    scheduler = None
    try:
        validated_bots = await _validate_bots(bots, settings)
        if not validated_bots:
            logger.error("Ни один bot не прошёл проверку токена — нечего обслуживать")
            return

        bots_by_tenant = await _resolve_bots_by_tenant(validated_bots, session_factory)
        scheduler = build_scheduler(bots_by_tenant, session_factory, settings)

        # Сбрасываем возможный вебхук на каждом боте, иначе long polling
        # не получит апдейты.
        for bot in validated_bots:
            await bot.delete_webhook(drop_pending_updates=False)
        scheduler.start()

        polling = asyncio.create_task(
            dispatcher.start_polling(
                *validated_bots,
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
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
        await dispatcher.storage.close()
        # dict.fromkeys, а не просто цикл по bots: с локальным Bot API server
        # все боты делят одну AiohttpSession, closing её дважды — лишний вызов.
        for session in dict.fromkeys(bot.session for bot in bots):
            await session.close()
        await engine.dispose()
        logger.info("Остановлено")


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
