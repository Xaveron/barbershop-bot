"""Валидация пользовательского ввода (админ-панель и текстовые шаги FSM)."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.bot.i18n import LANGUAGES, t

MAX_NAME_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 500
MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 480
MAX_PRICE = Decimal("100000")

_TIME_RANGE_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})\s*$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Только десятичные цифры: str.isdigit() пропускает «²» и подобное,
# на чём int() затем падает с ValueError.
_DIGITS_RE = re.compile(r"\d+")
# Ограничение на длину любого текстового ввода: сообщение в Telegram
# может быть до 4096 символов, а хранить и показывать столько незачем.
MAX_INPUT_LENGTH = 1000


class ValidationError(ValueError):
    """Ошибка валидации, текст которой безопасно показать пользователю."""


def clean_text(value: str, *, max_length: int = MAX_INPUT_LENGTH) -> str:
    """Убирает управляющие символы, лишние пробелы и обрезает слишком длинный ввод."""
    return _CONTROL_CHARS_RE.sub("", value).strip()[:max_length]


def validate_name(value: str, *, lang: str = "ru", field: str | None = None) -> str:
    """`field` — уже переведённое (вызывающей стороной) название поля,
    подставляемое в сообщение об ошибке; по умолчанию — общее «Название»
    на языке `lang` (Phase 9F: раньше было захардкожено по-русски для ЛЮБОГО
    вызывающего, включая админ-панель на ro/en — см. app/utils/validators.py
    audit)."""
    field_label = field if field is not None else t("validation.field_name_default", lang)
    name = clean_text(value)
    if len(name) < 2:
        raise ValidationError(t("validation.name_too_short", lang, field=field_label))
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(
            t("validation.name_too_long", lang, field=field_label, max=MAX_NAME_LENGTH)
        )
    return name


def validate_description(value: str, *, lang: str = "ru") -> str | None:
    text = clean_text(value)
    if text in {"", "-", "—"}:
        return None
    if len(text) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(
            t("validation.description_too_long", lang, max=MAX_DESCRIPTION_LENGTH)
        )
    return text


def validate_duration(value: str, *, lang: str = "ru") -> int:
    raw = clean_text(value).replace("мин", "").replace("min", "").strip()
    if not _DIGITS_RE.fullmatch(raw):
        raise ValidationError(t("validation.duration_format", lang))
    minutes = int(raw)
    if not MIN_DURATION_MINUTES <= minutes <= MAX_DURATION_MINUTES:
        raise ValidationError(
            t(
                "validation.duration_range",
                lang,
                min=MIN_DURATION_MINUTES,
                max=MAX_DURATION_MINUTES,
            )
        )
    if minutes % 5 != 0:
        raise ValidationError(t("validation.duration_step", lang))
    return minutes


def validate_price(value: str, *, lang: str = "ru") -> Decimal:
    raw = clean_text(value).replace(",", ".").replace(" ", "")
    try:
        price = Decimal(raw)
    except InvalidOperation as exc:
        raise ValidationError(t("validation.price_format", lang)) from exc
    # NaN и Infinity формально парсятся Decimal, но ломают сравнения и статистику.
    if not price.is_finite():
        raise ValidationError(t("validation.price_format", lang))
    if price < 0:
        raise ValidationError(t("validation.price_negative", lang))
    if price > MAX_PRICE:
        raise ValidationError(t("validation.price_too_high", lang, max=MAX_PRICE))
    return price.quantize(Decimal("0.01"))


_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def validate_phone(value: str, *, lang: str = "ru") -> str:
    """Телефон в свободной форме → нормализованный вид +37360111222."""
    raw = clean_text(value, max_length=32)
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.count("+") > 1 or ("+" in digits and not digits.startswith("+")):
        raise ValidationError(t("validation.phone_invalid", lang))
    if not _PHONE_RE.fullmatch(digits):
        raise ValidationError(t("validation.phone_invalid", lang))
    return digits


def validate_time_range(value: str, *, lang: str = "ru") -> tuple[time, time]:
    """Парсит '10:00-19:00' в пару time."""
    match = _TIME_RANGE_RE.match(clean_text(value))
    if not match:
        raise ValidationError(t("validation.time_range_format", lang))
    start_h, start_m, end_h, end_m = (int(group) for group in match.groups())
    if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
        raise ValidationError(t("validation.time_range_invalid", lang))
    start, end = time(start_h, start_m), time(end_h, end_m)
    if start >= end:
        raise ValidationError(t("validation.time_range_order", lang))
    return start, end


def validate_date(
    value: str,
    *,
    lang: str = "ru",
    not_before: date | None = None,
    max_days_ahead: int | None = None,
) -> date:
    raw = clean_text(value, max_length=32).replace("/", ".").replace("-", ".")
    parsed: date | None = None
    for fmt in ("%d.%m.%Y", "%Y.%m.%d", "%d.%m.%y"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValidationError(t("validation.date_format", lang))
    if not_before is not None and parsed < not_before:
        raise ValidationError(t("validation.date_past", lang))
    too_far = (
        max_days_ahead is not None
        and not_before is not None
        and (parsed - not_before).days > max_days_ahead
    )
    if too_far:
        raise ValidationError(t("validation.date_too_far", lang, max=max_days_ahead))
    return parsed


def validate_positive_int(value: str, *, field: str, lang: str = "ru") -> int:
    raw = clean_text(value)
    if not _DIGITS_RE.fullmatch(raw) or int(raw) <= 0:
        raise ValidationError(t("validation.positive_int", lang, field=field))
    return int(raw)


MAX_TELEGRAM_ID = 10**15


def validate_telegram_id(value: str, *, lang: str = "ru") -> int:
    """Числовой Telegram user ID (см. @userinfobot) — не username, не
    отображаемое имя. Верхняя граница — защита от переполнения/абсурдного
    ввода, а не реальный лимит Telegram (см. Phase 9A §H-1)."""
    raw = clean_text(value)
    if not _DIGITS_RE.fullmatch(raw):
        raise ValidationError(t("validation.telegram_id_not_a_number", lang))
    telegram_id = int(raw)
    if telegram_id <= 0 or telegram_id > MAX_TELEGRAM_ID:
        raise ValidationError(t("validation.telegram_id_invalid", lang))
    return telegram_id


def validate_timezone(value: str, *, lang: str = "ru") -> str:
    """IANA-идентификатор часового пояса, например Europe/Chisinau — та же
    проверка, что Settings._validate_timezone, но как переиспользуемая
    функция (см. docs/TENANT_ONBOARDING_DESIGN.md). Никаких смещений вида
    UTC+2 — только настоящие зоны, иначе DST не будет учитываться."""
    raw = clean_text(value, max_length=64)
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(t("validation.timezone_invalid", lang)) from exc
    return raw


def validate_currency(value: str, *, lang: str = "ru") -> str:
    """Трёхбуквенный код валюты (ISO 4217-стиль) — та же проверка, что
    Settings._validate_currency."""
    currency = clean_text(value, max_length=8).upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValidationError(t("validation.currency_invalid", lang))
    return currency


def validate_language(value: str, *, lang: str = "ru") -> str:
    """Код языка из app.bot.i18n.LANGUAGES — единственный канонический список
    поддерживаемых локалей (Phase 9E §5): не заводим здесь второй {"ru",
    "ro", "en"}, а импортируем существующий. app.config.settings.
    SUPPORTED_LANGUAGES остаётся отдельной копией намеренно (config не
    зависит от bot-слоя, см. её собственный комментарий) — тот случай
    дублирования, который спецификация фазы явно считает неизбежным."""
    code = clean_text(value, max_length=8).lower()
    if code not in LANGUAGES:
        raise ValidationError(
            t("validation.language_invalid", lang, languages=", ".join(LANGUAGES))
        )
    return code
