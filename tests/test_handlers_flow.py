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

from app.bot.i18n import t
from app.config import Settings
from app.database.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    BarberBranch,
    Branch,
    Role,
    Service,
    StaffMember,
    TelegramBotIdentity,
    Tenant,
    TenantStatus,
    User,
    WorkingSchedule,
)
from app.database.repositories import BranchRepository, StaffRepository
from app.utils.dt import combine_local, now_utc
from app.utils.text import TELEGRAM_TEXT_LIMIT

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — сквозные тесты пропущены"
)

ADMIN_ID = 990_001
CLIENT_ID = 990_002
STRANGER_ID = 990_003


@pytest.fixture(scope="module")
def settings(flow_settings: Settings) -> Settings:
    """Алиас на session-scoped tests/conftest.py::flow_settings (ADMIN_ID
    здесь совпадает с ADMIN_ID этого модуля, см. flow_settings)."""
    return flow_settings


@pytest.fixture(scope="module")
def session_factory(flow_session_factory):
    """Алиас на session-scoped tests/conftest.py::flow_session_factory —
    общий Dispatcher (см. dispatcher ниже) должен смотреть в ту же БД."""
    return flow_session_factory


@pytest.fixture(scope="module")
async def tenant_id(session_factory):
    """Отдельный арендатор на модуль — не пересекается с другими тестами/данными."""
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        tenant = Tenant(
            name=f"Flow Tenant {marker}", slug=f"flow-{marker}", status=TenantStatus.ACTIVE
        )
        session.add(tenant)
        await session.commit()
        tid = tenant.id

    yield tid

    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tid))
        await session.commit()


MOCKED_BOT_ID = 123456789  # см. tests/conftest.py::mocked_bot — id, разобранный из токена


@pytest.fixture(scope="module")
async def bot_identity(session_factory, tenant_id):
    """Phase 7: tenant_id больше не передаётся в build_dispatcher напрямую —
    BotIdentityMiddleware резолвит его через эту строку по bot.id мока."""
    async with session_factory() as session:
        session.add(
            TelegramBotIdentity(
                tenant_id=tenant_id, telegram_bot_id=MOCKED_BOT_ID, username="test_bot"
            )
        )
        await session.commit()


@pytest.fixture(scope="module")
def dispatcher(flow_dispatcher, tenant_id, bot_identity):
    """Алиас на session-scoped tests/conftest.py::flow_dispatcher (см. её
    докстринг: роутеры aiogram — модульные синглтоны, второй build_dispatcher()
    в процессе падает с RuntimeError, поэтому Dispatcher общий на весь прогон).
    tenant_id/bot_identity — зависимости по факту: гарантируют, что нужная
    строка TelegramBotIdentity уже есть в БД до первого feed_update."""
    return flow_dispatcher


@pytest.fixture
async def shop(session_factory, tenant_id):
    """Единственный активный филиал, барбер и услуга (в своём арендаторе).

    Один активный филиал — render_branch_or_skip выбирает его молча, так что
    сквозной сценарий записи остаётся прежним (без нового шага выбора филиала).
    """
    marker = uuid.uuid4().hex[:6]
    async with session_factory() as session:
        hidden_services = list(
            await session.scalars(
                select(Service).where(Service.tenant_id == tenant_id, Service.is_active)
            )
        )
        hidden_barbers = list(
            await session.scalars(
                select(Barber).where(Barber.tenant_id == tenant_id, Barber.is_active)
            )
        )
        for item in (*hidden_services, *hidden_barbers):
            item.is_active = False

        branch = Branch(tenant_id=tenant_id, name=f"Флоу-филиал {marker}")
        barber = Barber(tenant_id=tenant_id, name=f"Флоу-барбер {marker}")
        service = Service(
            tenant_id=tenant_id,
            name=f"Флоу-услуга {marker}",
            duration_minutes=60,
            price=Decimal("250.00"),
        )
        session.add_all([branch, barber, service])
        await session.flush()
        session.add(BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch.id))
        for weekday in range(7):
            session.add(
                WorkingSchedule(
                    tenant_id=tenant_id,
                    barber_id=barber.id,
                    branch_id=branch.id,
                    weekday=weekday,
                    start_time=time(10, 0),
                    end_time=time(19, 0),
                )
            )
        await session.commit()
        ids = (barber.id, service.id, branch.id)

    yield ids

    async with session_factory() as session:
        await session.execute(delete(Appointment).where(Appointment.barber_id == ids[0]))
        await session.execute(delete(WorkingSchedule).where(WorkingSchedule.barber_id == ids[0]))
        await session.execute(delete(BarberBranch).where(BarberBranch.barber_id == ids[0]))
        await session.execute(delete(Barber).where(Barber.id == ids[0]))
        await session.execute(delete(Service).where(Service.id == ids[1]))
        await session.execute(delete(Branch).where(Branch.id == ids[2]))
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
    barber_id, service_id, _ = shop

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
    barber_id, _, _ = shop
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
    barber_id, _, _ = shop
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
    barber_id, _, _ = shop
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
    barber_id, _, _ = shop
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


async def test_domain_error_is_translated(dispatcher, mocked_bot, session_factory, shop, tenant_id):
    """Ошибка сервисного слоя приходит клиенту на его языке, а не по-русски."""
    barber_id, service_id, branch_id = shop
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
                    tenant_id=tenant_id,
                    branch_id=branch_id,
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


# --- H-1: управление персоналом (Phase 9A) -----------------------------------
STAFF_OWNER_ID = 990_200
STAFF_MANAGER_ID = 990_201
NEW_STAFF_TG_ID = 990_202


@pytest.fixture
async def staff_pair(session_factory, tenant_id):
    """OWNER (MANAGE_STAFF) и MANAGER (VIEW_STAFF, но не MANAGE_STAFF) —
    намеренно НЕ через is_super_admin/ADMIN_ID, а через реальные роли, чтобы
    проверялась настоящая RBAC-ветка, а не платформенный обход."""
    async with session_factory() as session:
        repo = StaffRepository(session, tenant_id)
        await repo.create(telegram_id=STAFF_OWNER_ID, role=Role.TENANT_OWNER)
        await repo.create(telegram_id=STAFF_MANAGER_ID, role=Role.MANAGER)
        await session.commit()

    yield

    async with session_factory() as session:
        await session.execute(
            delete(StaffMember).where(
                StaffMember.telegram_id.in_(
                    (STAFF_OWNER_ID, STAFF_MANAGER_ID, NEW_STAFF_TG_ID)
                )
            )
        )
        await session.commit()


async def _add_staff_via_ui(
    dispatcher, mocked_bot, actor_id: int, telegram_id: int, role_value: str
) -> list[tuple[str, str | None]]:
    await feed(dispatcher, mocked_bot, make_callback("ad:stf_add:", actor_id))
    await feed(dispatcher, mocked_bot, make_message(str(telegram_id), actor_id))
    await feed(dispatcher, mocked_bot, make_callback(f"ad:stf_add_role:{role_value}", actor_id))
    return await feed(dispatcher, mocked_bot, make_callback("ad:stf_add_confirm:", actor_id))


async def test_manage_staff_can_add_staff(dispatcher, mocked_bot, shop, staff_pair):
    calls = await _add_staff_via_ui(
        dispatcher, mocked_bot, STAFF_OWNER_ID, NEW_STAFF_TG_ID, "receptionist"
    )
    assert str(NEW_STAFF_TG_ID) in texts(calls)
    assert "Ресепшн" in texts(calls)


async def test_view_staff_cannot_add_staff(dispatcher, mocked_bot, shop, staff_pair):
    calls = await _add_staff_via_ui(
        dispatcher, mocked_bot, STAFF_MANAGER_ID, NEW_STAFF_TG_ID, "receptionist"
    )
    assert calls == [("AnswerCallbackQuery", "Недостаточно прав.")]


async def test_manage_staff_can_change_role(dispatcher, mocked_bot, session_factory, tenant_id, shop, staff_pair):
    async with session_factory() as session:
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=NEW_STAFF_TG_ID, role=Role.MANAGER
        )
        await session.commit()
        staff_id = str(staff.id)

    await feed(dispatcher, mocked_bot, make_callback(f"ad:stf_role_pick:{staff_id}", STAFF_OWNER_ID))
    await feed(
        dispatcher, mocked_bot, make_callback(f"ad:stf_role_set:{staff_id}|receptionist", STAFF_OWNER_ID)
    )
    calls = await feed(
        dispatcher,
        mocked_bot,
        make_callback(f"ad:stf_role_confirm:{staff_id}|receptionist", STAFF_OWNER_ID),
    )
    assert "Ресепшн" in texts(calls)


async def test_manage_staff_can_deactivate(dispatcher, mocked_bot, session_factory, tenant_id, shop, staff_pair):
    async with session_factory() as session:
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=NEW_STAFF_TG_ID, role=Role.MANAGER
        )
        await session.commit()
        staff_id = str(staff.id)

    await feed(dispatcher, mocked_bot, make_callback(f"ad:stf_deact:{staff_id}", STAFF_OWNER_ID))
    calls = await feed(
        dispatcher, mocked_bot, make_callback(f"ad:stf_deact_ok:{staff_id}", STAFF_OWNER_ID)
    )
    assert "скрыт" in texts(calls)

    async with session_factory() as session:
        refreshed = await StaffRepository(session, tenant_id).get(staff.id)
        assert refreshed.is_active is False


async def test_view_staff_cannot_change_role_or_deactivate(
    dispatcher, mocked_bot, session_factory, tenant_id, shop, staff_pair
):
    async with session_factory() as session:
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=NEW_STAFF_TG_ID, role=Role.RECEPTIONIST
        )
        await session.commit()
        staff_id = str(staff.id)

    role_calls = await feed(
        dispatcher,
        mocked_bot,
        make_callback(f"ad:stf_role_confirm:{staff_id}|manager", STAFF_MANAGER_ID),
    )
    assert role_calls == [("AnswerCallbackQuery", "Недостаточно прав.")]

    deact_calls = await feed(
        dispatcher, mocked_bot, make_callback(f"ad:stf_deact_ok:{staff_id}", STAFF_MANAGER_ID)
    )
    assert deact_calls == [("AnswerCallbackQuery", "Недостаточно прав.")]

    async with session_factory() as session:
        refreshed = await StaffRepository(session, tenant_id).get(staff.id)
        assert refreshed.role == Role.RECEPTIONIST
        assert refreshed.is_active is True


async def test_sole_owner_cannot_be_demoted_or_deactivated_via_ui(
    dispatcher, mocked_bot, session_factory, tenant_id, shop, staff_pair
):
    async with session_factory() as session:
        owner = await StaffRepository(session, tenant_id).get_by_telegram_id(STAFF_OWNER_ID)
        owner_id = str(owner.id)

    role_calls = await feed(
        dispatcher,
        mocked_bot,
        make_callback(f"ad:stf_role_confirm:{owner_id}|manager", STAFF_OWNER_ID),
    )
    assert "единственный активный владелец" in texts(role_calls)

    deact_calls = await feed(
        dispatcher, mocked_bot, make_callback(f"ad:stf_deact_ok:{owner_id}", STAFF_OWNER_ID)
    )
    assert "единственный активный владелец" in texts(deact_calls)

    async with session_factory() as session:
        refreshed = await StaffRepository(session, tenant_id).get_by_telegram_id(STAFF_OWNER_ID)
        assert refreshed.role == Role.TENANT_OWNER
        assert refreshed.is_active is True


async def test_cross_tenant_staff_id_cannot_be_mutated_via_forged_callback(
    dispatcher, mocked_bot, session_factory, shop, staff_pair
):
    """Подделанный staff_id, принадлежащий ДРУГОМУ арендатору, не должен
    резолвиться через tenant_id текущего бота (см. Phase 9A §H-1/§6)."""
    other_tenant = Tenant(name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:8]}")
    async with session_factory() as session:
        session.add(other_tenant)
        await session.flush()
        foreign_staff = await StaffRepository(session, other_tenant.id).create(
            telegram_id=990_888_001, role=Role.MANAGER
        )
        await session.commit()
        foreign_id = str(foreign_staff.id)

    try:
        calls = await feed(
            dispatcher,
            mocked_bot,
            make_callback(f"ad:stf_role_pick:{foreign_id}", STAFF_OWNER_ID),
        )
        assert calls == [("AnswerCallbackQuery", "Сотрудник не найден.")]

        deact_calls = await feed(
            dispatcher, mocked_bot, make_callback(f"ad:stf_deact:{foreign_id}", STAFF_OWNER_ID)
        )
        assert deact_calls == [("AnswerCallbackQuery", "Сотрудник не найден.")]
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == other_tenant.id))
            await session.commit()


async def test_staff_branch_assignment_still_works(
    dispatcher, mocked_bot, session_factory, tenant_id, shop, staff_pair
):
    """Регрессия: существующая привязка сотрудника к филиалу (toggle_staff_branch)
    не должна быть сломана добавлением новых H-1 хендлеров."""
    _barber_id, _service_id, branch_id = shop
    async with session_factory() as session:
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=NEW_STAFF_TG_ID, role=Role.RECEPTIONIST
        )
        await session.commit()
        staff_id = str(staff.id)

    await feed(dispatcher, mocked_bot, make_callback(f"ad:stf:{staff_id}", STAFF_OWNER_ID))
    calls = await feed(
        dispatcher, mocked_bot, make_callback(f"ad:stf_branch:{branch_id}", STAFF_OWNER_ID)
    )
    assert "Сохранено" in [text for _, text in calls] or any(
        method == "AnswerCallbackQuery" and text == "Сохранено" for method, text in calls
    )
    async with session_factory() as session:
        assigned = await BranchRepository(session, tenant_id).list_branches_for_staff(staff.id)
    assert {b.id for b in assigned} == {branch_id}


# --- H-4: массовая отмена — branch/timezone safety (Phase 9A) ---------------
# tz_branch использует фиксированное смещение Etc/GMT+12 (без DST), заведомо
# далёкое от settings.tz (Europe/Chisinau, UTC+2/+3) — запись ставится на
# 12:00 по branch.tz, что соответствует уже СЛЕДУЮЩИМ суткам по Кишинёву.
# Если бы confirm/execute всё ещё считали окно в settings.tz (старый баг),
# эта запись не нашлась бы под тем же target_date — тест поймал бы регресс.
BULK_CANCEL_MANAGER_ID = 990_300


@pytest.fixture
async def tz_branch(session_factory, tenant_id, shop):
    _barber_id, service_id, _branch_id = shop
    marker = uuid.uuid4().hex[:6]
    async with session_factory() as session:
        branch = Branch(tenant_id=tenant_id, name=f"TZ-{marker}", timezone="Etc/GMT+12")
        barber = Barber(tenant_id=tenant_id, name=f"TZBarber-{marker}")
        client = User(
            tenant_id=tenant_id,
            telegram_id=990_300_000 + int(marker[:4], 16) % 1000,
            full_name="TZ Client",
        )
        session.add_all([branch, barber, client])
        await session.flush()
        session.add(BarberBranch(tenant_id=tenant_id, barber_id=barber.id, branch_id=branch.id))

        target_date = (now_utc().astimezone(branch.tz) + timedelta(days=3)).date()
        starts_at = combine_local(target_date, time(12, 0), branch.tz)
        appt = Appointment(
            tenant_id=tenant_id, branch_id=branch.id,
            user_id=client.id, barber_id=barber.id, service_id=service_id,
            starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED, price=Decimal("100"), duration_minutes=30,
        )
        session.add(appt)
        await session.commit()
        ids = {
            "branch_id": branch.id, "barber_id": barber.id, "appt_id": appt.id,
            "client_id": client.id, "target_date": target_date,
        }

    yield ids

    async with session_factory() as session:
        await session.execute(delete(Appointment).where(Appointment.id == ids["appt_id"]))
        await session.execute(delete(BarberBranch).where(BarberBranch.barber_id == ids["barber_id"]))
        await session.execute(delete(Barber).where(Barber.id == ids["barber_id"]))
        await session.execute(delete(User).where(User.id == ids["client_id"]))
        await session.execute(delete(Branch).where(Branch.id == ids["branch_id"]))
        await session.commit()


async def test_bulk_cancel_uses_branch_timezone_not_settings_tz(
    dispatcher, mocked_bot, session_factory, shop, tz_branch, staff_pair
):
    branch_id = tz_branch["branch_id"]
    target_date = tz_branch["target_date"]

    await feed(dispatcher, mocked_bot, make_callback("ad:bcx_days:", STAFF_OWNER_ID))
    candidates = [d for _, d in mocked_bot.buttons if d and d.startswith("ad:bcx_branch:")]
    target_button = next(c for c in candidates if c.endswith(str(branch_id)))
    await feed(dispatcher, mocked_bot, make_callback(target_button, STAFF_OWNER_ID))

    day_button = button(mocked_bot, "ad:bcx_conf:")
    assert day_button == f"ad:bcx_conf:{branch_id}|{target_date.isoformat()}"
    await feed(dispatcher, mocked_bot, make_callback(day_button, STAFF_OWNER_ID))

    confirm_button = button(mocked_bot, "ad:bcx_ok:")
    assert confirm_button == f"ad:bcx_ok:{branch_id}|{target_date.isoformat()}"
    calls = await feed(dispatcher, mocked_bot, make_callback(confirm_button, STAFF_OWNER_ID))
    assert "Отменено 1" in texts(calls)

    async with session_factory() as session:
        appt = await session.get(Appointment, tz_branch["appt_id"])
        assert appt.status == AppointmentStatus.CANCELLED


async def test_bulk_cancel_forged_branch_id_rejected_when_inaccessible(
    dispatcher, mocked_bot, session_factory, tenant_id, shop, tz_branch, staff_pair
):
    _barber_id, _service_id, shop_branch_id = shop
    async with session_factory() as session:
        manager = await StaffRepository(session, tenant_id).create(
            telegram_id=BULK_CANCEL_MANAGER_ID, role=Role.MANAGER
        )
        await session.commit()
        await BranchRepository(session, tenant_id).assign_staff(
            staff_member_id=manager.id, branch_id=shop_branch_id
        )
        await session.commit()

    try:
        branch_id = tz_branch["branch_id"]
        target_date = tz_branch["target_date"]
        forged_branch_calls = await feed(
            dispatcher,
            mocked_bot,
            make_callback(f"ad:bcx_branch:{branch_id}", BULK_CANCEL_MANAGER_ID),
        )
        assert "Недостаточно прав или филиал недоступен." in texts(forged_branch_calls)

        forged_conf_calls = await feed(
            dispatcher,
            mocked_bot,
            make_callback(
                f"ad:bcx_conf:{branch_id}|{target_date.isoformat()}", BULK_CANCEL_MANAGER_ID
            ),
        )
        assert "Недостаточно прав или филиал недоступен." in texts(forged_conf_calls)

        forged_ok_calls = await feed(
            dispatcher,
            mocked_bot,
            make_callback(
                f"ad:bcx_ok:{branch_id}|{target_date.isoformat()}", BULK_CANCEL_MANAGER_ID
            ),
        )
        assert "Недостаточно прав или филиал недоступен." in texts(forged_ok_calls)

        async with session_factory() as session:
            appt = await session.get(Appointment, tz_branch["appt_id"])
            assert appt.status == AppointmentStatus.CONFIRMED
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(StaffMember).where(StaffMember.telegram_id == BULK_CANCEL_MANAGER_ID)
            )
            await session.commit()


async def test_bulk_cancel_confirmation_cannot_be_replayed_against_another_branch(
    dispatcher, mocked_bot, session_factory, tenant_id, shop, tz_branch, staff_pair
):
    """Кнопка подтверждения несёт branch_id внутри себя (не из FSM state) —
    даже если сотрудник потом «заглянул» в другой филиал, старая кнопка
    продолжает относиться ровно к тому филиалу, для которого была показана."""
    barber_id, service_id, shop_branch_id = shop
    target_date = tz_branch["target_date"]
    # Запись в обычном филиале shop на ту же календарную дату (по его tz).
    async with session_factory() as session:
        client = await session.scalar(select(User).where(User.telegram_id == 990_301_555))
        if client is None:
            client = User(tenant_id=tenant_id, telegram_id=990_301_555, full_name="Shop client")
            session.add(client)
            await session.flush()
        branch = await session.get(Branch, shop_branch_id)
        starts_at = combine_local(target_date, time(12, 0), branch.tz)
        shop_appt = Appointment(
            tenant_id=tenant_id, branch_id=shop_branch_id,
            user_id=client.id, barber_id=barber_id, service_id=service_id,
            starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED, price=Decimal("100"), duration_minutes=30,
        )
        session.add(shop_appt)
        await session.commit()
        shop_appt_id = shop_appt.id

    try:
        branch_id = tz_branch["branch_id"]
        await feed(dispatcher, mocked_bot, make_callback(f"ad:bcx_branch:{branch_id}", STAFF_OWNER_ID))
        day_button = button(mocked_bot, "ad:bcx_conf:")
        await feed(dispatcher, mocked_bot, make_callback(day_button, STAFF_OWNER_ID))
        old_confirm_button = button(mocked_bot, "ad:bcx_ok:")
        assert old_confirm_button == f"ad:bcx_ok:{branch_id}|{target_date.isoformat()}"

        # Сотрудник «отвлёкся» — заглянул в другой филиал (но ничего там не подтверждал).
        await feed(
            dispatcher, mocked_bot, make_callback(f"ad:bcx_branch:{shop_branch_id}", STAFF_OWNER_ID)
        )

        # Возвращается к старой (уже показанной) кнопке подтверждения tz_branch.
        calls = await feed(dispatcher, mocked_bot, make_callback(old_confirm_button, STAFF_OWNER_ID))
        assert "Отменено 1" in texts(calls)

        async with session_factory() as session:
            tz_appt = await session.get(Appointment, tz_branch["appt_id"])
            reloaded_shop_appt = await session.get(Appointment, shop_appt_id)
        assert tz_appt.status == AppointmentStatus.CANCELLED
        assert reloaded_shop_appt.status == AppointmentStatus.CONFIRMED
    finally:
        async with session_factory() as session:
            await session.execute(delete(Appointment).where(Appointment.id == shop_appt_id))
            await session.execute(delete(User).where(User.id == client.id))
            await session.commit()


# --- M-4: VIEW_CUSTOMERS RBAC reconciliation (Phase 9B) ---------------------
RECEPTIONIST_ID = 990_600_001


@pytest.fixture
async def receptionist(session_factory, tenant_id):
    async with session_factory() as session:
        staff = await StaffRepository(session, tenant_id).create(
            telegram_id=RECEPTIONIST_ID, role=Role.RECEPTIONIST
        )
        await session.commit()
        staff_id = staff.id
    yield staff_id
    async with session_factory() as session:
        await session.execute(delete(StaffMember).where(StaffMember.id == staff_id))
        await session.commit()


async def test_receptionist_has_view_customers_can_open_client_list(
    dispatcher, mocked_bot, shop, receptionist
):
    """Пункт 1: роль с VIEW_CUSTOMERS (но без VIEW_ANALYTICS) теперь
    реально открывает список клиентов — раньше блокировалась router-level
    VIEW_ANALYTICS-фильтром (см. Phase 9B §M-4)."""
    calls = await feed(dispatcher, mocked_bot, make_callback("ad:clients:0", RECEPTIONIST_ID))
    assert calls != [("AnswerCallbackQuery", "Недостаточно прав.")]


async def test_stranger_without_view_customers_cannot_open_client_list(
    dispatcher, mocked_bot, shop
):
    """Пункт 2: без VIEW_CUSTOMERS (и без super_admin) экран по-прежнему
    закрыт."""
    calls = await feed(dispatcher, mocked_bot, make_callback("ad:clients:0", STRANGER_ID))
    assert calls == [("AnswerCallbackQuery", "Недостаточно прав.")]


async def test_receptionist_view_customers_does_not_grant_csv_export(
    dispatcher, mocked_bot, shop, receptionist
):
    """Пункт 3: VIEW_CUSTOMERS не расширяет MANAGE_CUSTOMERS — экспорт CSV
    (чувствительная массовая выгрузка) остаётся недоступен той же роли,
    которая уже может открыть список клиентов."""
    calls = await feed(dispatcher, mocked_bot, make_callback("ad:export:", RECEPTIONIST_ID))
    assert calls == [("AnswerCallbackQuery", "Недостаточно прав для экспорта.")]


async def test_receptionist_view_customers_does_not_grant_stats(
    dispatcher, mocked_bot, shop, receptionist
):
    """VIEW_CUSTOMERS != VIEW_ANALYTICS — статистика (agregированная бизнес-
    аналитика) остаётся отдельным правом, RECEPTIONIST его не имеет."""
    calls = await feed(dispatcher, mocked_bot, make_callback("ad:stats:", RECEPTIONIST_ID))
    assert calls == [("AnswerCallbackQuery", "Недостаточно прав.")]
