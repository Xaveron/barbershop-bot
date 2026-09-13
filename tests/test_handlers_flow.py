"""Сквозные тесты хендлеров: апдейт проходит через реальный Dispatcher.

Telegram заменён мок-сессией, база — настоящая (нужен TEST_DATABASE_URL
и применённые миграции). Проверяем маршрутизацию, middleware и права.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.bot.i18n import t
from app.config import Settings
from app.database import build_session_factory
from app.database.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    Service,
    User,
    WorkingSchedule,
)
from app.main import build_dispatcher
from app.utils.dt import now_utc
from app.utils.text import TELEGRAM_TEXT_LIMIT

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — сквозные тесты пропущены"
)

ADMIN_ID = 990_001
CLIENT_ID = 990_002
STRANGER_ID = 990_003


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
        ADMIN_ID=str(ADMIN_ID),
        TIMEZONE="Europe/Chisinau",
        # Троттлинг не должен мешать быстрым тестовым апдейтам.
        THROTTLE_INTERVAL=0.0,
        THROTTLE_BURST=100,
    )


@pytest.fixture(scope="module")
def session_factory(settings: Settings):
    """NullPool: у каждого теста свой event loop, соединения не переиспользуются."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    return build_session_factory(engine)


@pytest.fixture(scope="module")
def dispatcher(settings, session_factory):
    """Хендлер-роутеры aiogram — модульные синглтоны: Dispatcher создаём один раз."""
    return build_dispatcher(settings, session_factory)


@pytest.fixture
async def shop(session_factory):
    """Единственный активный барбер и единственная активная услуга."""
    marker = uuid.uuid4().hex[:6]
    async with session_factory() as session:
        hidden_services = list(await session.scalars(select(Service).where(Service.is_active)))
        hidden_barbers = list(await session.scalars(select(Barber).where(Barber.is_active)))
        for item in (*hidden_services, *hidden_barbers):
            item.is_active = False

        barber = Barber(name=f"Флоу-барбер {marker}")
        service = Service(
            name=f"Флоу-услуга {marker}", duration_minutes=60, price=Decimal("250.00")
        )
        session.add_all([barber, service])
        await session.flush()
        for weekday in range(7):
            session.add(
                WorkingSchedule(
                    barber_id=barber.id,
                    weekday=weekday,
                    start_time=time(10, 0),
                    end_time=time(19, 0),
                )
            )
        await session.commit()
        ids = (barber.id, service.id)

    yield ids

    async with session_factory() as session:
        await session.execute(delete(Appointment).where(Appointment.barber_id == ids[0]))
        await session.execute(delete(WorkingSchedule).where(WorkingSchedule.barber_id == ids[0]))
        await session.execute(delete(Barber).where(Barber.id == ids[0]))
        await session.execute(delete(Service).where(Service.id == ids[1]))
        for item in (*hidden_services, *hidden_barbers):
            restored = await session.get(type(item), item.id)
            if restored is not None:
                restored.is_active = True
        await session.commit()


def make_message(
    text: str, user_id: int, chat_type: str = "private", language: str | None = None
) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=user_id, type=chat_type),
        from_user=TgUser(
            id=user_id,
            is_bot=False,
            first_name="Тест",
            username="tester",
            language_code=language,
        ),
        text=text,
    )


def make_callback(data: str, user_id: int) -> CallbackQuery:
    message = Message(
        message_id=2,
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=0, is_bot=True, first_name="Bot"),
        text="предыдущее сообщение",
    )
    return CallbackQuery(
        id=uuid.uuid4().hex,
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест", username="tester"),
        chat_instance="x",
        message=message,
        data=data,
    )


async def feed(dispatcher, bot, event) -> list[tuple[str, str | None]]:
    bot.calls.clear()
    update = (
        Update(update_id=1, message=event)
        if isinstance(event, Message)
        else Update(update_id=1, callback_query=event)
    )
    await dispatcher.feed_update(bot, update)
    return list(bot.calls)


def texts(calls: list[tuple[str, str | None]]) -> str:
    return " | ".join(text or "" for _, text in calls)


def labels(bot) -> list[str]:
    return [label for label, _ in bot.buttons]


def button(bot, prefix: str, index: int = 0) -> str:
    matching = [data for _, data in bot.buttons if data and data.startswith(prefix)]
    assert matching, f"не найдено кнопок с префиксом {prefix}: {bot.buttons}"
    return matching[index]


# --- Базовая маршрутизация --------------------------------------------------
async def test_start_greets_and_shows_menu(dispatcher, mocked_bot, shop):
    calls = await feed(dispatcher, mocked_bot, make_message("/start", CLIENT_ID))
    assert calls[0][0] == "SendMessage"
    assert "Barbershop" in texts(calls)
    assert any(data == "m:book" for _, data in mocked_bot.buttons)


async def test_unknown_callback_does_not_crash(dispatcher, mocked_bot, shop):
    calls = await feed(dispatcher, mocked_bot, make_callback("zz:unknown", CLIENT_ID))
    assert calls[0][0] == "AnswerCallbackQuery"
    assert "устарела" in texts(calls)


# --- Личные чаты ------------------------------------------------------------
async def test_group_chat_updates_are_ignored(dispatcher, mocked_bot, session_factory, shop):
    """В группе карточки записей видели бы все участники — не отвечаем на кнопки."""
    from app.database.models import User

    group_user_id = 990_777
    await feed(
        dispatcher, mocked_bot, make_callback("m:my", group_user_id)
    )  # приватный колбэк, чтобы юзер появился
    mocked_bot.calls.clear()

    group_message = make_message("привет", group_user_id, chat_type="supergroup")
    calls = await feed(dispatcher, mocked_bot, group_message)
    assert calls == [], "обычное сообщение из группы должно игнорироваться молча"

    group_command = make_message("/start", group_user_id, chat_type="group")
    calls = await feed(dispatcher, mocked_bot, group_command)
    assert "только в личных сообщениях" in texts(calls)

    async with session_factory() as session:
        await session.execute(delete(User).where(User.telegram_id == group_user_id))
        await session.commit()


# --- Права администратора ---------------------------------------------------
async def test_admin_panel_is_closed_for_regular_user(dispatcher, mocked_bot, shop):
    calls = await feed(dispatcher, mocked_bot, make_callback("ad:stats:", STRANGER_ID))
    assert calls == [("AnswerCallbackQuery", "Недостаточно прав.")]

    calls = await feed(dispatcher, mocked_bot, make_message("/admin", STRANGER_ID))
    assert "только администратору" in texts(calls)


async def test_admin_panel_opens_for_admin(dispatcher, mocked_bot, shop):
    calls = await feed(dispatcher, mocked_bot, make_message("/admin", ADMIN_ID))
    assert "Админ-панель" in texts(calls)


async def test_admin_cannot_be_faked_by_callback_data(dispatcher, mocked_bot, shop):
    """Права проверяются по from_user, а не по содержимому callback_data."""
    calls = await feed(
        dispatcher, mocked_bot, make_callback(f"ad:appt_cancel:{uuid.uuid4()}", STRANGER_ID)
    )
    assert calls == [("AnswerCallbackQuery", "Недостаточно прав.")]


# --- Сценарий записи --------------------------------------------------------
async def test_full_booking_flow_creates_appointment(
    dispatcher, mocked_bot, session_factory, shop, settings
):
    barber_id, service_id = shop

    await feed(dispatcher, mocked_bot, make_message("/start", CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback("m:book", CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "sv:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "br:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "dt:"), CLIENT_ID))
    calls = await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "tm:"), CLIENT_ID))

    # Карточка подтверждения из ТЗ.
    summary = texts(calls)
    assert "💈" in summary and "👨‍💈" in summary and "💰" in summary and "⏱" in summary
    assert [data for _, data in mocked_bot.buttons] == ["cf:yes", "cf:no"]

    calls = await feed(dispatcher, mocked_bot, make_callback("cf:yes", CLIENT_ID))
    assert "подтверждена" in texts(calls).lower()

    async with session_factory() as session:
        appointments = list(
            await session.scalars(select(Appointment).where(Appointment.barber_id == barber_id))
        )
    assert len(appointments) == 1
    assert appointments[0].service_id == service_id
    assert appointments[0].status == AppointmentStatus.CONFIRMED


async def test_double_tap_on_confirm_does_not_duplicate_appointment(
    dispatcher, mocked_bot, session_factory, shop
):
    barber_id, _ = shop
    await feed(dispatcher, mocked_bot, make_message("/start", CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback("m:book", CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "sv:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "br:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "dt:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "tm:"), CLIENT_ID))

    first, second = await asyncio.gather(
        feed(dispatcher, mocked_bot, make_callback("cf:yes", CLIENT_ID)),
        feed(dispatcher, mocked_bot, make_callback("cf:yes", CLIENT_ID)),
    )

    async with session_factory() as session:
        appointments = list(
            await session.scalars(select(Appointment).where(Appointment.barber_id == barber_id))
        )
    assert len(appointments) == 1, texts(first) + " || " + texts(second)


async def test_client_sees_only_own_appointments(
    dispatcher, mocked_bot, session_factory, shop
):
    """Чужая запись не появляется в «Мои записи» и не открывается по прямому id."""
    barber_id, _ = shop
    await feed(dispatcher, mocked_bot, make_message("/start", CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback("m:book", CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "sv:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "br:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "dt:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "tm:"), CLIENT_ID))
    await feed(dispatcher, mocked_bot, make_callback("cf:yes", CLIENT_ID))

    async with session_factory() as session:
        appointment = (
            await session.scalars(select(Appointment).where(Appointment.barber_id == barber_id))
        ).one()

    calls = await feed(dispatcher, mocked_bot, make_callback("m:my", STRANGER_ID))
    assert "нет активных записей" in texts(calls)

    calls = await feed(
        dispatcher, mocked_bot, make_callback(f"ap:view:{appointment.id}", STRANGER_ID)
    )
    assert "не найдена" in texts(calls)

    calls = await feed(
        dispatcher, mocked_bot, make_callback(f"ap:cancel_ok:{appointment.id}", STRANGER_ID)
    )
    assert "не найдена" in texts(calls).lower()

    async with session_factory() as session:
        untouched = await session.get(Appointment, appointment.id)
        assert untouched.status == AppointmentStatus.CONFIRMED


# --- Лимиты Telegram --------------------------------------------------------
async def test_outgoing_text_is_clipped_to_telegram_limit(mocked_bot):
    """Страховка на исходящих: длинный список не должен ронять отправку."""
    await mocked_bot.send_message(1, "<b>строка</b>\n" * 2000)
    _, sent = mocked_bot.calls[-1]
    assert len(sent) <= TELEGRAM_TEXT_LIMIT
    assert sent.count("<b>") == sent.count("</b>")


# --- Мультиязычность --------------------------------------------------------
async def test_language_is_taken_from_telegram_profile(dispatcher, mocked_bot, shop):
    """Румыноязычный клиент видит бота на румынском без единой настройки."""
    calls = await feed(dispatcher, mocked_bot, make_message("/start", 990_101, language="ro"))
    assert "Salut" in texts(calls)
    assert any(label == t("btn.book", "ro") for label, _ in mocked_bot.buttons)


async def test_client_can_switch_language_and_choice_persists(
    dispatcher, mocked_bot, session_factory, shop
):
    # Свежий telegram_id: выбранный язык сохраняется в БД и пережил бы прогон.
    user_id = 991_000 + uuid.uuid4().int % 1000
    await feed(dispatcher, mocked_bot, make_message("/start", user_id))
    calls = await feed(dispatcher, mocked_bot, make_callback("m:language", user_id))
    assert t("language.choose", "ru") in texts(calls)

    calls = await feed(dispatcher, mocked_bot, make_callback("lg:en", user_id))
    assert "English" in texts(calls)
    assert any(label == t("btn.book", "en") for label, _ in mocked_bot.buttons)

    # Выбор сохранён в базе и переживает следующий апдейт от Telegram с ru-профилем.
    async with session_factory() as session:
        stored = await session.scalar(select(User).where(User.telegram_id == user_id))
        assert stored.language_code == "en"

    calls = await feed(dispatcher, mocked_bot, make_message("/start", user_id, language="ru"))
    assert "Hi," in texts(calls)

    async with session_factory() as session:
        await session.execute(delete(User).where(User.telegram_id == user_id))
        await session.commit()


async def test_booking_flow_runs_in_english(dispatcher, mocked_bot, session_factory, shop):
    barber_id, _ = shop
    user_id = 990_103

    await feed(dispatcher, mocked_bot, make_message("/start", user_id, language="en"))
    await feed(dispatcher, mocked_bot, make_callback("m:book", user_id))
    assert t("booking.step_service", "en") in texts(mocked_bot.calls)

    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "sv:"), user_id))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "br:"), user_id))
    calls = await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "dt:"), user_id))
    # Даты и подписи кнопок тоже на английском.
    assert t("booking.step_time", "en") in texts(calls)
    assert any(label == t("btn.back", "en") for label, _ in mocked_bot.buttons)

    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "tm:"), user_id))
    calls = await feed(dispatcher, mocked_bot, make_callback("cf:yes", user_id))
    assert "Booking confirmed" in texts(calls)

    async with session_factory() as session:
        appointment = (
            await session.scalars(select(Appointment).where(Appointment.barber_id == barber_id))
        ).one()
    assert appointment.status == AppointmentStatus.CONFIRMED


async def test_booking_flow_runs_in_romanian(dispatcher, mocked_bot, session_factory, shop):
    barber_id, _ = shop
    user_id = 990_105

    await feed(dispatcher, mocked_bot, make_message("/start", user_id, language="ro"))
    await feed(dispatcher, mocked_bot, make_callback("m:book", user_id))
    assert t("booking.step_service", "ro") in texts(mocked_bot.calls)

    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "sv:"), user_id))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "br:"), user_id))
    calls = await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "dt:"), user_id))
    assert t("booking.step_time", "ro") in texts(calls)
    assert any(label == t("btn.back", "ro") for label, _ in mocked_bot.buttons)

    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "tm:"), user_id))
    calls = await feed(dispatcher, mocked_bot, make_callback("cf:yes", user_id))
    assert "confirmată" in texts(calls).lower()

    async with session_factory() as session:
        appointment = (
            await session.scalars(select(Appointment).where(Appointment.barber_id == barber_id))
        ).one()
    assert appointment.status == AppointmentStatus.CONFIRMED


async def test_domain_error_is_translated(dispatcher, mocked_bot, session_factory, shop):
    """Ошибка сервисного слоя приходит клиенту на его языке, а не по-русски."""
    barber_id, service_id = shop
    user_id = 990_104
    await feed(dispatcher, mocked_bot, make_message("/start", user_id, language="ro"))

    # Упираемся в лимит активных записей: три штуки уже есть.
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        base = now_utc() + timedelta(days=1)
        for index in range(3):
            start_at = base + timedelta(hours=index * 2)
            session.add(
                Appointment(
                    user_id=user.id,
                    barber_id=barber_id,
                    service_id=service_id,
                    starts_at=start_at,
                    ends_at=start_at + timedelta(minutes=60),
                    status=AppointmentStatus.CONFIRMED,
                    price=Decimal("250.00"),
                    duration_minutes=60,
                )
            )
        await session.commit()

    await feed(dispatcher, mocked_bot, make_callback("m:book", user_id))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "sv:"), user_id))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "br:"), user_id))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "dt:"), user_id))
    await feed(dispatcher, mocked_bot, make_callback(button(mocked_bot, "tm:"), user_id))
    calls = await feed(dispatcher, mocked_bot, make_callback("cf:yes", user_id))

    answer = texts(calls)
    assert "programări active" in answer, answer
    assert "активных записей" not in answer
