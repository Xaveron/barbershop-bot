"""Хелперы форматирования текста для HTML parse_mode."""

from __future__ import annotations

import html
import re
from decimal import Decimal

# Лимиты Telegram: 4096 символов на текст сообщения, 1024 — на подпись.
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
_UNCLOSED_TAG_RE = re.compile(r"<[^>]*$")
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
_VOID_TAGS = frozenset({"br", "hr", "img"})
# Excel и LibreOffice исполняют содержимое ячейки, начинающееся с этих символов.
_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def esc(value: object) -> str:
    """Экранирование пользовательских данных перед вставкой в HTML-сообщение."""
    return html.escape(str(value), quote=False)


def money(amount: Decimal | float | int, currency: str = "MDL") -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    text = f"{value:,.2f}".replace(",", " ")
    if text.endswith(".00"):
        text = text[:-3]
    return f"{text} {currency}"


def pluralize(number: int, one: str, few: str, many: str) -> str:
    """Русская плюрализация: 1 запись, 2 записи, 5 записей."""
    n = abs(number) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def clip(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> str:
    """Обрезает текст до лимита Telegram, не разрывая HTML-тег.

    Режем по границе строки, если она есть: наши сообщения построчные,
    и теги внутри строки остаются парными.
    """
    if len(text) <= limit:
        return text
    suffix = "\n…"
    head = text[: limit - len(suffix)]
    newline = head.rfind("\n")
    head = head[:newline] if newline > limit // 2 else _UNCLOSED_TAG_RE.sub("", head)

    # Telegram отклоняет сообщение с незакрытым тегом — дозакрываем сами,
    # оставив под закрывающие теги место в пределах лимита.
    closings = _closing_tags(head)
    overflow = len(head) + len(closings) + len(suffix) - limit
    if overflow > 0:
        head = _UNCLOSED_TAG_RE.sub("", head[:-overflow])
        closings = _closing_tags(head)
    return (head + closings + suffix)[:limit]


def _closing_tags(html_text: str) -> str:
    stack: list[str] = []
    for match in _TAG_RE.finditer(html_text):
        closing, tag = match.group(1), match.group(2).lower()
        if tag in _VOID_TAGS:
            continue
        if not closing:
            stack.append(tag)
        elif tag in stack:
            stack.reverse()
            stack.remove(tag)
            stack.reverse()
    return "".join(f"</{tag}>" for tag in reversed(stack))


def csv_safe(value: object) -> str:
    """Нейтрализует формулы в CSV: клиент управляет своим именем в Telegram."""
    text = str(value)
    if text and text[0] in _CSV_DANGEROUS_PREFIXES:
        return "'" + text
    return text
