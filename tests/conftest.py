"""Общие фикстуры. Тесты не требуют ни PostgreSQL, ни Telegram."""

from __future__ import annotations

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.types import Chat, Message
from aiogram.types import User as TgUser

from app.bot.middlewares import TextLimitMiddleware

# Значения окружения должны существовать до импорта настроек приложения.
os.environ.setdefault("BOT_TOKEN", "123456789:TEST-TOKEN-FOR-UNIT-TESTS-ONLY")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("ADMIN_ID", "1001,1002")
os.environ.setdefault("TIMEZONE", "Europe/Chisinau")

TZ = ZoneInfo("Europe/Chisinau")


@pytest.fixture
def tz() -> ZoneInfo:
    return TZ


@pytest.fixture
def work_window():
    from app.services.slots import WorkWindow

    return WorkWindow(start=time(10, 0), end=time(19, 0))


def local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class MockedSession(BaseSession):
    """Сессия Telegram, которая ничего не отправляет, а записывает вызовы."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str | None]] = []
        self.buttons: list[tuple[str, str | None]] = []

    async def close(self) -> None:  # pragma: no cover - интерфейс BaseSession
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        name = type(method).__name__
        text = getattr(method, "text", None)
        self.calls.append((name, text))
        markup = getattr(method, "reply_markup", None)
        if markup is not None and getattr(markup, "inline_keyboard", None):
            self.buttons[:] = [
                (button.text, button.callback_data)
                for row in markup.inline_keyboard
                for button in row
            ]
        if name == "GetMe":
            return TgUser(id=1, is_bot=True, first_name="Bot", username="test_bot")
        if name in {"SendMessage", "EditMessageText"}:
            return Message(
                message_id=1,
                date=datetime.now(tz=TZ),
                chat=Chat(id=1, type="private"),
                text=text or "ok",
            )
        return True


@pytest.fixture
async def mocked_bot():
    session = MockedSession()
    bot = Bot(
        token="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # Та же обвязка, что и в app.main: страховка по длине текста.
    bot.session.middleware(TextLimitMiddleware())
    bot.calls = session.calls  # удобный доступ из тестов
    bot.buttons = session.buttons
    bot.mocked_session = session
    yield bot
    await bot.session.close()
