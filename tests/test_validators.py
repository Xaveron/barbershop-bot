"""Тесты валидации пользовательского ввода."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from app.utils.validators import (
    ValidationError,
    clean_text,
    validate_date,
    validate_description,
    validate_duration,
    validate_name,
    validate_price,
    validate_time_range,
)


def test_clean_text_strips_control_characters():
    assert clean_text("  Стрижка\x00\x07  ") == "Стрижка"


@pytest.mark.parametrize("value", ["", "a", " ", "x" * 121])
def test_invalid_names_rejected(value):
    with pytest.raises(ValidationError):
        validate_name(value)


def test_valid_name_normalized():
    assert validate_name("  Мужская стрижка  ") == "Мужская стрижка"


@pytest.mark.parametrize("value", ["0", "-30", "abc", "3", "1000", "47"])
def test_invalid_durations_rejected(value):
    with pytest.raises(ValidationError):
        validate_duration(value)


def test_valid_duration():
    assert validate_duration("45 мин") == 45


@pytest.mark.parametrize("value", ["-1", "abc", "999999"])
def test_invalid_prices_rejected(value):
    with pytest.raises(ValidationError):
        validate_price(value)


def test_price_accepts_comma_decimal():
    assert validate_price("250,50") == Decimal("250.50")


@pytest.mark.parametrize("value", ["19:00-10:00", "10:00", "25:00-26:00", "abc", "10:00-10:00"])
def test_invalid_time_ranges_rejected(value):
    with pytest.raises(ValidationError):
        validate_time_range(value)


def test_valid_time_range():
    assert validate_time_range(" 10.00 - 19:30 ") == (time(10, 0), time(19, 30))


def test_date_parsing_formats():
    assert validate_date("25.12.2026") == date(2026, 12, 25)
    assert validate_date("2026-12-25") == date(2026, 12, 25)


def test_invalid_date_rejected():
    with pytest.raises(ValidationError):
        validate_date("32.13.2026")


def test_description_placeholder_becomes_none():
    assert validate_description("-") is None
    assert validate_description("Классная услуга") == "Классная услуга"
