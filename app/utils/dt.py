"""Работа с датой/временем и локализованное форматирование.

Правило проекта: в БД всё хранится в UTC (timestamptz),
пользователю показывается локальное время барбершопа (settings.timezone)
на его языке (ru / ro / en).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

DEFAULT_LANG = "ru"

# Названия месяцев в форме, пригодной для «15 сентября» / «15 septembrie».
MONTHS: dict[str, tuple[str, ...]] = {
    "ru": (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ),
    "ro": (
        "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
        "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
}

WEEKDAYS_SHORT_BY_LANG: dict[str, tuple[str, ...]] = {
    "ru": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"),
    "ro": ("Lu", "Ma", "Mi", "Jo", "Vi", "Sâ", "Du"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}

WEEKDAYS_FULL_BY_LANG: dict[str, tuple[str, ...]] = {
    "ru": (
        "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье",
    ),
    "ro": ("Luni", "Marți", "Miercuri", "Joi", "Vineri", "Sâmbătă", "Duminică"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}

DURATION_UNITS: dict[str, tuple[str, str]] = {
    "ru": ("ч", "мин"),
    "ro": ("h", "min"),
    "en": ("h", "min"),
}

# Совместимость с кодом, которому нужен русский список без указания языка.
MONTHS_GENITIVE: dict[int, str] = dict(enumerate(MONTHS["ru"], start=1))
WEEKDAYS_SHORT: tuple[str, ...] = WEEKDAYS_SHORT_BY_LANG["ru"]
WEEKDAYS_FULL: tuple[str, ...] = WEEKDAYS_FULL_BY_LANG["ru"]


def _lang(lang: str | None) -> str:
    return lang if lang in MONTHS else DEFAULT_LANG


def month_name(month: int, lang: str = DEFAULT_LANG) -> str:
    return MONTHS[_lang(lang)][month - 1]


def weekday_short(weekday: int, lang: str = DEFAULT_LANG) -> str:
    return WEEKDAYS_SHORT_BY_LANG[_lang(lang)][weekday]


def weekday_full(weekday: int, lang: str = DEFAULT_LANG) -> str:
    return WEEKDAYS_FULL_BY_LANG[_lang(lang)][weekday]


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def today_in(tz: ZoneInfo) -> date:
    return now_utc().astimezone(tz).date()


def to_local(value: datetime, tz: ZoneInfo) -> datetime:
    """Переводит datetime в локальную зону, наивное значение считается UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(tz)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Ожидается datetime с таймзоной")
    return value.astimezone(UTC)


def combine_local(day: date, moment: time, tz: ZoneInfo) -> datetime:
    """Собирает локальный aware-datetime из даты и времени."""
    return datetime.combine(day, moment, tzinfo=tz)


def format_day(value: date, lang: str = DEFAULT_LANG) -> str:
    """15 сентября / 15 septembrie / 15 September"""
    return f"{value.day} {month_name(value.month, lang)}"


def format_day_with_weekday(value: date, lang: str = DEFAULT_LANG) -> str:
    """15 сентября (Пн)"""
    return f"{format_day(value, lang)} ({weekday_short(value.weekday(), lang)})"


def format_time(value: datetime | time) -> str:
    return value.strftime("%H:%M")


def format_datetime(value: datetime, tz: ZoneInfo, lang: str = DEFAULT_LANG) -> str:
    """15 сентября, 14:30"""
    local = to_local(value, tz)
    return f"{format_day(local.date(), lang)}, {format_time(local)}"


def format_duration(minutes: int, lang: str = DEFAULT_LANG) -> str:
    hour_unit, minute_unit = DURATION_UNITS[_lang(lang)]
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} {hour_unit} {mins} {minute_unit}"
    if hours:
        return f"{hours} {hour_unit}"
    return f"{mins} {minute_unit}"


def hhmm_to_time(value: str) -> time:
    """Парсит '1430' или '14:30' в time."""
    cleaned = value.replace(":", "").strip()
    if len(cleaned) != 4 or not cleaned.isdigit():
        raise ValueError(f"Некорректное время: {value!r}")
    hour, minute = int(cleaned[:2]), int(cleaned[2:])
    return time(hour=hour, minute=minute)


def time_to_hhmm(value: datetime | time) -> str:
    """Компактное представление для callback_data (лимит 64 байта)."""
    return value.strftime("%H%M")
