"""Настройка логирования с маскированием секретов."""

from __future__ import annotations

import logging
import re
import sys
from typing import Final

_TOKEN_RE: Final = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
_DSN_RE: Final = re.compile(r"(?P<scheme>\w+(?:\+\w+)?://)(?P<user>[^:/@\s]+):(?P<pwd>[^@/\s]+)@")
_SECRET_KV_RE: Final = re.compile(
    r"(?i)\b(bot_token|token|password|passwd|secret|api_key)\b\s*[=:]\s*\S+"
)


def mask_secrets(text: str) -> str:
    """Убирает токены/пароли из строки перед записью в лог."""
    text = _TOKEN_RE.sub("<BOT_TOKEN>", text)
    text = _DSN_RE.sub(lambda m: f"{m.group('scheme')}{m.group('user')}:***@", text)
    return _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}=***", text)


class SecretsFilter(logging.Filter):
    """Фильтр, который маскирует секреты в сообщении и аргументах записи."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: mask_secrets(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    mask_secrets(arg) if isinstance(arg, str) else arg for arg in record.args
                )
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(SecretsFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
