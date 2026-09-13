"""Тесты мультиязычности: полнота словарей, подстановки, выбор языка."""

from __future__ import annotations

import re
from datetime import date

import pytest

from app.bot.i18n import (
    FALLBACK_LANGUAGE,
    LANGUAGE_NAMES,
    LANGUAGES,
    TRANSLATIONS,
    normalize_language,
    t,
)
from app.bot.keyboards.client import main_menu_kb
from app.bot.texts import FAQ_KEYS, contacts_text, faq_text
from app.config import Settings
from app.database.models import AppointmentStatus
from app.services.formatting import status_label, summary_block
from app.utils.dt import (
    format_day,
    format_day_with_weekday,
    format_duration,
    month_name,
    weekday_full,
    weekday_short,
)
from tests.conftest import local

PLACEHOLDER_RE = re.compile(r"{(\w+)}")


def make_settings(**kwargs) -> Settings:
    base = {
        "BOT_TOKEN": "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "ADMIN_ID": "1",
        "TIMEZONE": "Europe/Chisinau",
    }
    base.update(kwargs)
    return Settings(**base)


# --- Полнота словарей -------------------------------------------------------
def test_all_locales_are_registered():
    assert set(TRANSLATIONS) == set(LANGUAGES) == set(LANGUAGE_NAMES)
    assert FALLBACK_LANGUAGE in TRANSLATIONS


@pytest.mark.parametrize("lang", LANGUAGES)
def test_locales_have_identical_key_sets(lang):
    """Забытый ключ в одном языке — самый частый баг перевода."""
    reference = set(TRANSLATIONS[FALLBACK_LANGUAGE])
    assert set(TRANSLATIONS[lang]) == reference


@pytest.mark.parametrize("lang", LANGUAGES)
def test_placeholders_match_across_locales(lang):
    """{minutes}, {barber}, {count} должны совпадать во всех переводах."""
    for key, template in TRANSLATIONS[FALLBACK_LANGUAGE].items():
        expected = set(PLACEHOLDER_RE.findall(template))
        actual = set(PLACEHOLDER_RE.findall(TRANSLATIONS[lang][key]))
        assert actual == expected, f"{key} ({lang})"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_no_empty_translations(lang):
    assert all(value.strip() for value in TRANSLATIONS[lang].values())


@pytest.mark.parametrize("lang", LANGUAGES)
def test_html_tags_are_balanced(lang):
    for key, template in TRANSLATIONS[lang].items():
        assert template.count("<b>") == template.count("</b>"), key
        assert template.count("<i>") == template.count("</i>"), key


# Аббревиатуры, которые намеренно совпадают во всех языках.
SHARED_KEYS = {"btn.faq"}


def test_translations_differ_between_languages():
    """Защита от «перевода» копипастой."""
    same = [
        key
        for key in TRANSLATIONS["en"]
        if key not in SHARED_KEYS and TRANSLATIONS["ru"][key] == TRANSLATIONS["en"][key]
    ]
    # Совпадать могут только строки без слов (эмодзи, символы).
    assert all(not re.search(r"[A-Za-zА-Яа-я]{3,}", TRANSLATIONS["ru"][key]) for key in same), same


# --- Выбор языка ------------------------------------------------------------
@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ru", "ru"),
        ("ru-RU", "ru"),
        ("RU_ru", "ru"),
        ("ro", "ro"),
        ("ro-MD", "ro"),
        ("mo", "ro"),  # устаревший код Молдовы
        ("en", "en"),
        ("en-GB", "en"),
    ],
)
def test_normalize_language_maps_telegram_codes(code, expected):
    assert normalize_language(code) == expected


@pytest.mark.parametrize("code", [None, "", "fr", "zh-CN", "  "])
def test_unsupported_language_falls_back_to_default(code):
    assert normalize_language(code, "ro") == "ro"
    assert normalize_language(code) == "ru"


def test_unknown_default_falls_back_to_english():
    assert normalize_language(None, "fr") == FALLBACK_LANGUAGE


# --- Подстановка ------------------------------------------------------------
def test_translation_with_parameters():
    assert "14" in t("rule.cancel_deadline", "en", minutes=14)
    assert "14" in t("rule.cancel_deadline", "ro", minutes=14)


def test_missing_key_returns_key_itself():
    assert t("nope.nothing", "ru") == "nope.nothing"


def test_missing_parameters_do_not_crash():
    assert t("rule.cancel_deadline", "ru") == TRANSLATIONS["ru"]["rule.cancel_deadline"]


def test_unknown_language_uses_fallback_catalog():
    assert t("btn.book", "fr") == TRANSLATIONS[FALLBACK_LANGUAGE]["btn.book"]


# --- Даты и длительность ----------------------------------------------------
@pytest.mark.parametrize(
    ("lang", "expected"),
    [("ru", "15 сентября"), ("ro", "15 septembrie"), ("en", "15 September")],
)
def test_dates_are_localized(lang, expected):
    assert format_day(date(2026, 9, 15), lang) == expected


def test_weekday_names_are_localized():
    assert weekday_full(0, "ru") == "Понедельник"
    assert weekday_full(0, "ro") == "Luni"
    assert weekday_full(0, "en") == "Monday"
    assert weekday_short(6, "en") == "Sun"
    assert month_name(12, "ro") == "decembrie"


def test_day_with_weekday_is_localized():
    assert format_day_with_weekday(date(2026, 9, 15), "en") == "15 September (Tue)"


@pytest.mark.parametrize(
    ("lang", "expected"), [("ru", "1 ч 30 мин"), ("ro", "1 h 30 min"), ("en", "1 h 30 min")]
)
def test_duration_is_localized(lang, expected):
    assert format_duration(90, lang) == expected


def test_unknown_language_in_dates_falls_back():
    assert format_day(date(2026, 9, 15), "fr") == "15 сентября"


# --- Карточки и составные тексты -------------------------------------------
@pytest.mark.parametrize("lang", LANGUAGES)
def test_summary_block_keeps_layout_in_every_language(lang):
    block = summary_block(
        service_name="Fade",
        barber_name="Ion",
        start_local=local(2026, 9, 15, 14, 30),
        price=250,
        currency="MDL",
        duration_minutes=60,
        lang=lang,
    )
    lines = block.splitlines()
    assert len(lines) == 6
    assert lines[0].startswith("💈") and lines[3] == "🕐 14:30"
    assert "250 MDL" in lines[4]


@pytest.mark.parametrize("lang", LANGUAGES)
def test_status_labels_exist_for_every_status(lang):
    for status in AppointmentStatus:
        label = status_label(status, lang)
        assert label and not label.startswith("status.")


@pytest.mark.parametrize("lang", LANGUAGES)
def test_faq_is_rendered_with_settings(lang):
    settings = make_settings()
    text = faq_text(settings, lang)
    assert str(settings.cancel_min_lead_minutes) in text
    assert str(settings.booking_horizon_days) in text
    assert text.count("<b>") == len(FAQ_KEYS) + 1  # заголовок + вопросы


@pytest.mark.parametrize("lang", LANGUAGES)
def test_contacts_use_shop_settings(lang):
    settings = make_settings(SHOP_NAME="Barber Ion", SHOP_MAPS_URL="https://maps.example/x")
    text = contacts_text(settings, ["Luni: 10:00–19:00"], lang)
    assert "Barber Ion" in text
    assert "https://maps.example/x" in text
    assert "Luni: 10:00–19:00" in text


# --- Клавиатуры -------------------------------------------------------------
@pytest.mark.parametrize("lang", LANGUAGES)
def test_main_menu_is_translated_and_has_language_button(lang):
    keyboard = main_menu_kb(lang, is_admin=False)
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    labels = [b.text for b in buttons]
    assert TRANSLATIONS[lang]["btn.book"] in labels
    assert TRANSLATIONS[lang]["btn.language"] in labels
    assert all(b.callback_data for b in buttons)


def test_admin_button_appears_only_for_admin():
    labels = [b.text for row in main_menu_kb("ru", is_admin=True).inline_keyboard for b in row]
    assert TRANSLATIONS["ru"]["btn.admin"] in labels
    labels = [b.text for row in main_menu_kb("ru", is_admin=False).inline_keyboard for b in row]
    assert TRANSLATIONS["ru"]["btn.admin"] not in labels


# --- Уведомления ------------------------------------------------------------
NOTIFY_KEYS = (
    "notify.reminder_24h",
    "notify.reminder_2h",
    "notify.new_appointment",
    "notify.cancelled_by_client",
    "notify.cancelled_by_admin",
    "notify.client_moved",
)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_all_notify_keys_are_translated(lang):
    for key in NOTIFY_KEYS:
        text = t(key, lang)
        assert text and not text.startswith("notify."), f"{key} не переведён для {lang}"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_notify_reminder_texts_mention_time(lang):
    # 24h — переведено как «завтра»/«mâine»/«tomorrow», а не «24 часа»
    assert t("notify.reminder_24h", lang) != t("notify.reminder_2h", lang)
    # 2h-напоминание содержит «2»
    assert "2" in t("notify.reminder_2h", lang)


def test_notify_keys_differ_across_languages():
    for key in NOTIFY_KEYS:
        assert TRANSLATIONS["ru"][key] != TRANSLATIONS["en"][key], (
            f"{key}: русский и английский совпадают"
        )
