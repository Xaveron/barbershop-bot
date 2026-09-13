"""Мультиязычность: русский, румынский, английский.

Правила:
- язык клиента хранится в `users.language_code` и меняется кнопкой «🌐 Язык»;
- при первом контакте берётся из профиля Telegram, иначе — DEFAULT_LANGUAGE;
- если ключа нет в выбранном языке, берём английский, затем сам ключ
  (так отсутствующий перевод виден в тестах, но не ломает ответ бота).
"""

from __future__ import annotations

import logging
from typing import Final

from app.bot.i18n.locales.en import MESSAGES as EN
from app.bot.i18n.locales.ro import MESSAGES as RO
from app.bot.i18n.locales.ru import MESSAGES as RU

logger = logging.getLogger(__name__)

LANGUAGES: Final[tuple[str, ...]] = ("ru", "ro", "en")
FALLBACK_LANGUAGE: Final[str] = "en"

LANGUAGE_NAMES: Final[dict[str, str]] = {
    "ru": "🇷🇺 Русский",
    "ro": "🇷🇴 Română",
    "en": "🇬🇧 English",
}

TRANSLATIONS: Final[dict[str, dict[str, str]]] = {"ru": RU, "ro": RO, "en": EN}

# Телеграм присылает коды вида "ru-RU", "ro", "mo" (устаревший код Молдовы).
_ALIASES: Final[dict[str, str]] = {"mo": "ro", "md": "ro", "rum": "ro", "rus": "ru", "eng": "en"}


def normalize_language(code: str | None, default: str = "ru") -> str:
    """Приводит код языка Telegram к поддерживаемому."""
    if not code:
        return default if default in LANGUAGES else FALLBACK_LANGUAGE
    base = code.strip().lower().replace("_", "-").split("-")[0]
    base = _ALIASES.get(base, base)
    if base in LANGUAGES:
        return base
    return default if default in LANGUAGES else FALLBACK_LANGUAGE


def t(key: str, lang: str = "ru", /, **params: object) -> str:
    """Возвращает перевод по ключу с подстановкой параметров."""
    catalog = TRANSLATIONS.get(lang) or TRANSLATIONS[FALLBACK_LANGUAGE]
    template = catalog.get(key)
    if template is None:
        template = TRANSLATIONS[FALLBACK_LANGUAGE].get(key)
    if template is None:
        logger.warning("Нет перевода для ключа %s (язык %s)", key, lang)
        return key
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        logger.warning("Не хватает параметров для ключа %s (язык %s)", key, lang)
        return template


__all__ = [
    "FALLBACK_LANGUAGE",
    "LANGUAGES",
    "LANGUAGE_NAMES",
    "TRANSLATIONS",
    "normalize_language",
    "t",
]
