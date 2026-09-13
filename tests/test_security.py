"""Тесты защиты: экранирование, лимиты, валидация, права доступа, троттлинг."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from aiogram.types import CallbackQuery, Chat, Message
from aiogram.types import User as TgUser

from app.bot.keyboards.admin import (
    admin_appointment_kb,
    admin_appointments_kb,
    admin_barber_kb,
    admin_barbers_kb,
    admin_service_kb,
    admin_services_kb,
    exceptions_kb,
    week_kb,
    weekday_actions_kb,
)
from app.bot.keyboards.callbacks import (
    AdmCB,
    AdmDayCB,
    ApptCB,
    BarberCB,
    ConfirmCB,
    DayCB,
    MenuCB,
    NavCB,
    ServiceCB,
    TimeCB,
)
from app.bot.keyboards.client import (
    appointment_actions_kb,
    barbers_kb,
    cancel_confirm_kb,
    days_kb,
    my_appointments_kb,
    services_kb,
    times_kb,
)
from app.bot.middlewares import IsAdmin, ThrottlingMiddleware
from app.bot.utils import parse_uuid
from app.config import Settings
from app.database.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    ScheduleException,
    Service,
)
from app.services.formatting import summary_block
from app.utils.text import TELEGRAM_TEXT_LIMIT, clip, csv_safe, esc
from app.utils.validators import (
    MAX_INPUT_LENGTH,
    ValidationError,
    clean_text,
    validate_date,
    validate_duration,
    validate_name,
    validate_positive_int,
    validate_price,
)
from tests.conftest import local

CALLBACK_LIMIT = 64
INJECTION = '<a href="https://evil.example">Жми сюда</a>'


def make_settings(admin_id: str = "111111") -> Settings:
    return Settings(
        BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
        ADMIN_ID=admin_id,
        TIMEZONE="Europe/Chisinau",
    )


# --- HTML-инъекции ----------------------------------------------------------
def test_user_controlled_names_are_escaped_in_cards():
    """Имя барбера/услуги приходит от админа, имя клиента — из профиля Telegram."""
    block = summary_block(
        service_name=INJECTION,
        barber_name="<b>Иван",
        start_local=local(2026, 9, 15, 14, 30),
        price=Decimal("250"),
        currency="MDL",
        duration_minutes=60,
    )
    assert "<a href" not in block
    assert "<b>" not in block
    assert "&lt;a href=" in block


def test_esc_keeps_text_readable():
    assert esc("Стрижка & борода") == "Стрижка &amp; борода"


# --- Лимиты Telegram --------------------------------------------------------
def test_clip_respects_hard_limit():
    assert len(clip("а" * 10_000)) <= TELEGRAM_TEXT_LIMIT


def test_clip_does_not_leave_unclosed_tags():
    clipped = clip("<b>" + "x" * TELEGRAM_TEXT_LIMIT)
    assert clipped.count("<b>") == clipped.count("</b>")
    assert not clipped.rstrip().endswith("<b")


def test_clip_balances_nested_tags():
    clipped = clip("<b><i>" + "y" * TELEGRAM_TEXT_LIMIT)
    assert clipped.endswith("</i></b>\n…")


def test_clip_keeps_short_text_untouched():
    text = "💇 <b>Услуги</b>\nСтрижка — 250 MDL"
    assert clip(text) == text


def test_clip_cuts_long_list_on_line_boundary():
    clipped = clip("<b>Услуга</b> — 250 MDL\n" * 500)
    assert "</b>" in clipped
    assert clipped.endswith("…")
    assert len(clipped) <= TELEGRAM_TEXT_LIMIT


# --- CSV-инъекции -----------------------------------------------------------
@pytest.mark.parametrize("payload", ["=1+1", "+1", "-1+1", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_csv_formula_payloads_are_neutralized(payload):
    assert csv_safe(payload).startswith("'")


def test_csv_safe_keeps_normal_values():
    assert csv_safe("Иван Петров") == "Иван Петров"
    assert csv_safe(250) == "250"


def test_exported_cell_is_not_a_formula_after_sanitizing():
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";").writerow([csv_safe('=HYPERLINK("http://evil","click")')])
    assert not buffer.getvalue().lstrip('"').startswith("=")


# --- callback_data ----------------------------------------------------------
def test_all_callback_factories_fit_telegram_limit():
    sample = str(uuid.uuid4())
    payloads = [
        MenuCB(action="contacts"),
        ServiceCB(id=sample),
        BarberCB(id=sample),
        DayCB(value="2026-12-31"),
        TimeCB(value="1430"),
        ConfirmCB(action="yes"),
        NavCB(to="service"),
        ApptCB(action="cancel_ok", id=sample),
        AdmCB(action="appt_cancel", arg=sample),
        AdmCB(action="sch_set", arg=f"{sample}|6"),
        AdmCB(action="svc_del_ok", arg=sample),
        AdmDayCB(barber=sample, weekday=6),
    ]
    for payload in payloads:
        packed = payload.pack()
        assert len(packed.encode()) <= CALLBACK_LIMIT, packed


def make_service() -> Service:
    return Service(
        id=uuid.uuid4(),
        name="Мужская стрижка" * 5,
        duration_minutes=60,
        price=Decimal("250.00"),
        currency="MDL",
        is_active=True,
        sort_order=10,
    )


def make_barber() -> Barber:
    return Barber(id=uuid.uuid4(), name="Иван" * 20, is_active=True, sort_order=10)


def make_appointment() -> Appointment:
    service, barber = make_service(), make_barber()
    start = local(2026, 9, 15, 12, 0)
    appointment = Appointment(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=start,
        ends_at=start + timedelta(minutes=60),
        status=AppointmentStatus.CONFIRMED,
        price=Decimal("250.00"),
        currency="MDL",
        duration_minutes=60,
    )
    appointment.service = service
    appointment.barber = barber
    return appointment


def test_keyboards_produce_valid_callback_data(tz):
    sample = str(uuid.uuid4())
    service, barber = make_service(), make_barber()
    appointment = make_appointment()
    exception = ScheduleException(
        id=uuid.uuid4(), barber_id=barber.id, exception_date=date(2026, 12, 31), is_day_off=True
    )
    keyboards = [
        appointment_actions_kb(sample, "ru"),
        cancel_confirm_kb(sample, "ru"),
        services_kb([service], "ru"),
        barbers_kb([barber], "ru"),
        days_kb([date(2026, 9, 15)], "ru", back_to="service"),
        times_kb([local(2026, 9, 15, 9, 5)], "ru", back_to="day"),
        my_appointments_kb([appointment], tz, "ru"),
        admin_services_kb([service]),
        admin_service_kb(service),
        admin_barbers_kb([barber]),
        admin_barber_kb(barber),
        week_kb(sample, dict.fromkeys(range(7))),
        weekday_actions_kb(sample, 6),
        exceptions_kb([exception]),
        admin_appointments_kb([appointment], tz, page=0, has_next=True),
        admin_appointment_kb(sample),
    ]
    for keyboard in keyboards:
        for row in keyboard.inline_keyboard:
            for button in row:
                assert button.callback_data is not None
                assert len(button.callback_data.encode()) <= CALLBACK_LIMIT


@pytest.mark.parametrize(
    "raw",
    ["", "not-a-uuid", "../../etc/passwd", "1' OR '1'='1", "0" * 200, None],
)
def test_parse_uuid_rejects_garbage(raw):
    assert parse_uuid(raw) is None


# --- Валидация ввода --------------------------------------------------------
@pytest.mark.parametrize("payload", ["NaN", "nan", "Infinity", "-Infinity", "1e999"])
def test_price_rejects_non_finite_numbers(payload):
    """Decimal('NaN') проходит парсинг, но ломает сравнения и статистику."""
    with pytest.raises(ValidationError):
        validate_price(payload)


@pytest.mark.parametrize("payload", ["²", "½", "¹⁰", "٤٥٩٩٩"])
def test_duration_rejects_non_decimal_digits(payload):
    """str.isdigit() пропускает такие символы, а int() на них падает."""
    with pytest.raises(ValidationError):
        validate_duration(payload)


def test_positive_int_rejects_non_decimal_digits():
    with pytest.raises(ValidationError):
        validate_positive_int("²", field="Число")


def test_clean_text_caps_input_length():
    assert len(clean_text("я" * 10_000)) == MAX_INPUT_LENGTH


def test_name_rejects_overlong_input():
    with pytest.raises(ValidationError):
        validate_name("я" * 500)


def test_clean_text_strips_zero_width_and_control_chars():
    assert clean_text("\x00\x1fСтрижка\x7f") == "Стрижка"


def test_exception_date_must_not_be_in_the_past():
    today = date(2026, 9, 13)
    with pytest.raises(ValidationError):
        validate_date("01.01.2020", not_before=today, max_days_ahead=180)


def test_exception_date_must_stay_within_horizon():
    today = date(2026, 9, 13)
    with pytest.raises(ValidationError):
        validate_date("01.01.2030", not_before=today, max_days_ahead=180)
    assert validate_date("20.09.2026", not_before=today, max_days_ahead=180) == date(2026, 9, 20)


# --- Права администратора ---------------------------------------------------
def make_message(user_id: int) -> Message:
    return Message(
        message_id=1,
        date=local(2026, 9, 13, 12, 0),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест"),
        text="/admin",
    )


async def test_is_admin_allows_only_configured_ids():
    filter_ = IsAdmin()
    settings = make_settings("111111,222222")
    assert await filter_(make_message(111111), settings=settings)
    assert await filter_(make_message(222222), settings=settings)
    assert not await filter_(make_message(333333), settings=settings)


async def test_is_admin_denies_when_admin_id_is_empty():
    """Пустой ADMIN_ID не должен означать «админ каждый»."""
    settings = make_settings("")
    assert settings.admin_ids == ()
    assert not await IsAdmin()(make_message(111111), settings=settings)


async def test_is_admin_denies_without_settings_in_context():
    assert not await IsAdmin()(make_message(111111), settings=None)


def test_admin_ids_ignore_garbage_entries():
    settings = make_settings(" 111111 , , abc , 222222 ")
    assert settings.admin_ids == (111111, 222222)


# --- Троттлинг --------------------------------------------------------------
def make_callback(user_id: int) -> CallbackQuery:
    message = Message(
        message_id=2,
        date=local(2026, 9, 13, 12, 0),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=0, is_bot=True, first_name="Bot"),
        text="prev",
    )
    return CallbackQuery(
        id="1",
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест"),
        chat_instance="x",
        message=message,
        data="m:book",
    )


async def test_throttling_blocks_burst_and_isolates_users(mocked_bot):
    middleware = ThrottlingMiddleware(interval=0.0, burst=3, window=60.0)
    handled: list[int] = []

    async def handler(event, data):
        handled.append(data["event_from_user"].id)
        return "handled"

    attacker = make_callback(500).as_(mocked_bot)
    for _ in range(6):
        await middleware(handler, attacker, {"event_from_user": attacker.from_user})

    assert len(handled) == 3, "после burst апдейты должны отбрасываться"

    victim = make_callback(600).as_(mocked_bot)
    result = await middleware(handler, victim, {"event_from_user": victim.from_user})
    assert result == "handled", "лимит одного пользователя не влияет на другого"


async def test_throttled_user_gets_feedback(mocked_bot):
    """Молчаливый дроп оставлял бы у пользователя вечный «часик» на кнопке."""
    middleware = ThrottlingMiddleware(interval=10.0, burst=1, window=60.0)

    async def handler(event, data):
        return "handled"

    callback = make_callback(700).as_(mocked_bot)
    data = {"event_from_user": callback.from_user}
    await middleware(handler, callback, data)
    mocked_bot.calls.clear()
    await middleware(handler, callback, data)

    assert [name for name, _ in mocked_bot.calls] == ["AnswerCallbackQuery"]


# --- Прочее -----------------------------------------------------------------
def test_settings_never_exposes_token_in_repr():
    settings = make_settings()
    assert "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw" not in repr(settings)


def test_reminder_offsets_cover_24h_and_2h():
    from app.services.booking import REMINDER_OFFSETS

    assert [offset for _, offset in REMINDER_OFFSETS] == [
        int(timedelta(hours=24).total_seconds() // 60),
        int(timedelta(hours=2).total_seconds() // 60),
    ]


def test_working_hours_validation_rejects_reversed_range():
    from app.utils.validators import validate_time_range

    assert validate_time_range("10:00-19:00") == (time(10, 0), time(19, 0))
    with pytest.raises(ValidationError):
        validate_time_range("19:00-10:00")
