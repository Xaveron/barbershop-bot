"""Тесты форматирования и утилит времени."""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.bot.i18n import LANGUAGES, t
from app.database.models import AppointmentStatus
from app.services.formatting import appointment_card, appointment_line, summary_block
from app.utils.dt import (
    format_datetime,
    format_day,
    format_duration,
    format_time,
    hhmm_to_time,
    time_to_hhmm,
    to_local,
)
from app.utils.logging import mask_secrets
from app.utils.text import esc, money, pluralize
from tests.conftest import TZ, local


def _make_appointment(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
    *,
    service_name: str = "Стрижка",
    barber_name: str = "Иван",
    price: Decimal = Decimal("250"),
    currency: str = "MDL",
    duration_minutes: int = 60,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
) -> MagicMock:
    appt = MagicMock()
    appt.starts_at = local(year, month, day, hour, minute).astimezone(UTC)
    appt.service.name = service_name
    appt.barber.name = barber_name
    appt.price = price
    appt.currency = currency
    appt.duration_minutes = duration_minutes
    appt.status = status
    return appt


def test_summary_block_matches_expected_layout():
    block = summary_block(
        service_name="Стрижка",
        barber_name="Иван",
        start_local=local(2026, 9, 15, 14, 30),
        price=Decimal("250"),
        currency="MDL",
        duration_minutes=60,
    )
    assert block.splitlines() == [
        "💈 Стрижка",
        "👨‍💈 Иван",
        "📅 15 сентября",
        "🕐 14:30",
        "💰 250 MDL",
        "⏱ 1 ч",
    ]


def test_utc_stored_time_is_rendered_in_shop_timezone(tz):
    stored = datetime(2026, 9, 15, 11, 30, tzinfo=UTC)  # летом Кишинёв = UTC+3
    assert format_time(to_local(stored, tz)) == "14:30"


def test_hhmm_roundtrip():
    assert hhmm_to_time("1430") == time(14, 30)
    assert hhmm_to_time("14:30") == time(14, 30)
    assert time_to_hhmm(time(9, 5)) == "0905"


@pytest.mark.parametrize("value", ["99", "abcd", "1:30"])
def test_invalid_hhmm_rejected(value):
    with pytest.raises(ValueError):
        hhmm_to_time(value)


def test_format_helpers():
    assert format_day(local(2026, 9, 15, 10).date()) == "15 сентября"
    assert format_duration(90) == "1 ч 30 мин"
    assert format_duration(45) == "45 мин"
    assert money(Decimal("250.00")) == "250 MDL"
    assert money(Decimal("250.50"), "EUR") == "250.50 EUR"


def test_pluralize():
    assert pluralize(1, "запись", "записи", "записей") == "запись"
    assert pluralize(3, "запись", "записи", "записей") == "записи"
    assert pluralize(11, "запись", "записи", "записей") == "записей"


def test_html_escaping_of_user_input():
    assert esc("<b>hack</b>") == "&lt;b&gt;hack&lt;/b&gt;"


def test_logging_masks_secrets():
    masked = mask_secrets(
        "token=123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw "
        "postgresql+asyncpg://user:supersecret@db:5432/app"
    )
    assert "supersecret" not in masked
    assert "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw" not in masked


def test_logging_masks_dsn_password_containing_at_sign():
    """Пароль с '@' — самый первый '@' не должен путаться с разделителем хоста."""
    masked = mask_secrets("postgresql+asyncpg://user:p@ssword@db:5432/app")
    assert "ssword" not in masked
    assert masked == "postgresql+asyncpg://user:***@db:5432/app"


# --- format_datetime ---------------------------------------------------------
def test_format_datetime_converts_utc_to_local_and_localizes():
    stored = datetime(2026, 9, 15, 11, 30, tzinfo=UTC)  # летом Кишинёв UTC+3
    assert format_datetime(stored, TZ, "ru") == "15 сентября, 14:30"
    assert format_datetime(stored, TZ, "ro") == "15 septembrie, 14:30"
    assert format_datetime(stored, TZ, "en") == "15 September, 14:30"


# --- appointment_line --------------------------------------------------------
@pytest.mark.parametrize(
    ("lang", "month_word"),
    [("ru", "сентября"), ("ro", "septembrie"), ("en", "September")],
)
def test_appointment_line_is_localized(lang, month_word):
    appt = _make_appointment(2026, 9, 15, 11, 0)
    line = appointment_line(appt, TZ, lang)
    assert month_word in line
    assert "11:00" in line
    assert "Стрижка" in line and "Иван" in line


def test_appointment_line_format_has_separator():
    appt = _make_appointment(2026, 9, 15, 11, 0)
    line = appointment_line(appt, TZ)
    assert " — " in line and "/" in line


# --- appointment_card --------------------------------------------------------
@pytest.mark.parametrize("lang", LANGUAGES)
def test_appointment_card_has_six_lines_without_status(lang):
    appt = _make_appointment(2026, 9, 15, 14, 30)
    card = appointment_card(appt, TZ, with_status=False, lang=lang)
    assert len(card.splitlines()) == 6


@pytest.mark.parametrize("lang", LANGUAGES)
def test_appointment_card_appends_localized_status(lang):
    appt = _make_appointment(2026, 9, 15, 14, 30, status=AppointmentStatus.CONFIRMED)
    card = appointment_card(appt, TZ, with_status=True, lang=lang)
    assert len(card.splitlines()) == 7
    assert t("status.confirmed", lang) in card


@pytest.mark.parametrize(
    ("status", "key"),
    [
        (AppointmentStatus.CANCELLED, "status.cancelled"),
        (AppointmentStatus.COMPLETED, "status.completed"),
        (AppointmentStatus.NO_SHOW, "status.no_show"),
    ],
)
def test_appointment_card_status_labels_all_statuses(status, key):
    appt = _make_appointment(2026, 9, 15, 14, 30, status=status)
    for lang in LANGUAGES:
        card = appointment_card(appt, TZ, with_status=True, lang=lang)
        assert t(key, lang) in card
