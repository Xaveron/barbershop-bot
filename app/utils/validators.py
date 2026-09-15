"""Валидация пользовательского ввода (админ-панель и текстовые шаги FSM)."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def validate_name(value: str, *, field: str = "Название") -> str:
    name = clean_text(value)
    if len(name) < 2:
        raise ValidationError(f"{field} слишком короткое (минимум 2 символа).")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"{field} слишком длинное (максимум {MAX_NAME_LENGTH} символов).")
    return name


def validate_description(value: str) -> str | None:
    text = clean_text(value)
    if text in {"", "-", "—"}:
        return None
    if len(text) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(f"Описание длиннее {MAX_DESCRIPTION_LENGTH} символов.")
    return text


def validate_duration(value: str) -> int:
    raw = clean_text(value).replace("мин", "").strip()
    if not _DIGITS_RE.fullmatch(raw):
        raise ValidationError("Длительность указывается целым числом минут, например: 45")
    minutes = int(raw)
    if not MIN_DURATION_MINUTES <= minutes <= MAX_DURATION_MINUTES:
        raise ValidationError(
            f"Длительность должна быть от {MIN_DURATION_MINUTES} до {MAX_DURATION_MINUTES} минут."
        )
    if minutes % 5 != 0:
        raise ValidationError("Длительность должна быть кратна 5 минутам.")
    return minutes


def validate_price(value: str) -> Decimal:
    raw = clean_text(value).replace(",", ".").replace(" ", "")
    try:
        price = Decimal(raw)
    except InvalidOperation as exc:
        raise ValidationError("Цена указывается числом, например: 250 или 250.50") from exc
    # NaN и Infinity формально парсятся Decimal, но ломают сравнения и статистику.
    if not price.is_finite():
        raise ValidationError("Цена указывается числом, например: 250 или 250.50")
    if price < 0:
        raise ValidationError("Цена не может быть отрицательной.")
    if price > MAX_PRICE:
        raise ValidationError(f"Цена не может превышать {MAX_PRICE}.")
    return price.quantize(Decimal("0.01"))


_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def validate_phone(value: str) -> str:
    """Телефон в свободной форме → нормализованный вид +37360111222."""
    raw = clean_text(value, max_length=32)
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.count("+") > 1 or ("+" in digits and not digits.startswith("+")):
        raise ValidationError("Некорректный номер телефона.")
    if not _PHONE_RE.fullmatch(digits):
        raise ValidationError("Некорректный номер телефона.")
    return digits


def validate_time_range(value: str) -> tuple[time, time]:
    """Парсит '10:00-19:00' в пару time."""
    match = _TIME_RANGE_RE.match(clean_text(value))
    if not match:
        raise ValidationError("Формат рабочих часов: 10:00-19:00")
    start_h, start_m, end_h, end_m = (int(group) for group in match.groups())
    if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
        raise ValidationError("Некорректное время. Часы 0-23, минуты 0-59.")
    start, end = time(start_h, start_m), time(end_h, end_m)
    if start >= end:
        raise ValidationError("Начало рабочего дня должно быть раньше конца.")
    return start, end


def validate_date(
    value: str,
    *,
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
        raise ValidationError("Формат даты: ДД.ММ.ГГГГ, например 25.12.2026")
    if not_before is not None and parsed < not_before:
        raise ValidationError("Дата уже прошла — укажите сегодняшний день или позже.")
    too_far = (
        max_days_ahead is not None
        and not_before is not None
        and (parsed - not_before).days > max_days_ahead
    )
    if too_far:
        raise ValidationError(f"Дата слишком далеко: максимум {max_days_ahead} дней вперёд.")
    return parsed


def validate_positive_int(value: str, *, field: str) -> int:
    raw = clean_text(value)
    if not _DIGITS_RE.fullmatch(raw) or int(raw) <= 0:
        raise ValidationError(f"{field} должно быть положительным целым числом.")
    return int(raw)


def validate_timezone(value: str) -> str:
    """IANA-идентификатор часового пояса, например Europe/Chisinau — та же
    проверка, что Settings._validate_timezone, но как переиспользуемая
    функция (см. docs/TENANT_ONBOARDING_DESIGN.md). Никаких смещений вида
    UTC+2 — только настоящие зоны, иначе DST не будет учитываться."""
    raw = clean_text(value, max_length=64)
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(
            "Некорректный часовой пояс. Укажите IANA-идентификатор, "
            "например Europe/Chisinau или Europe/Bucharest."
        ) from exc
    return raw


def validate_currency(value: str) -> str:
    """Трёхбуквенный код валюты (ISO 4217-стиль) — та же проверка, что
    Settings._validate_currency."""
    currency = clean_text(value, max_length=8).upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValidationError("Валюта — трёхбуквенный код, например MDL, RON или EUR.")
    return currency
