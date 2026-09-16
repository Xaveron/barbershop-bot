"""Интеграционные тесты branch-scoped отчётности (Phase 9A §C-1) на реальном
PostgreSQL: статистика, список клиентов, экспорт CSV должны учитывать
branch-level authorization так же, как это уже делает admin/appointments.py.

Запускаются, только если задан TEST_DATABASE_URL и в базе применены миграции
(см. заголовок tests/test_integration_booking.py).
"""

from __future__ import annotations

import csv
import io
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.config import Settings
from app.database import build_engine, build_session_factory
from app.database.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    BarberBranch,
    Branch,
    Role,
    Service,
    StaffMember,
    Tenant,
    User,
)
from app.database.repositories import (
    AppointmentRepository,
    BranchRepository,
    StaffRepository,
    UserRepository,
)
from app.services.authorization import resolve_accessible_branch_ids
from app.services.export import ExportService
from app.services.stats import StatsService
from app.utils.dt import now_utc

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — интеграционные тесты пропущены"
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        DATABASE_URL=TEST_DATABASE_URL or "postgresql+asyncpg://x:x@localhost/x",
        ADMIN_ID="111111",
        TIMEZONE="Europe/Chisinau",
    )


@pytest.fixture
async def engine(settings: Settings):
    engine = build_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return build_session_factory(engine)


@pytest.fixture
async def tenant_id(session_factory):
    marker = uuid.uuid4().hex[:8]
    async with session_factory() as session:
        tenant = Tenant(name=f"Reports Tenant {marker}", slug=f"reports-{marker}")
        session.add(tenant)
        await session.commit()
        tid = tenant.id
    yield tid
    async with session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tid))
        await session.commit()


@pytest.fixture
async def two_branch_shop(session_factory, tenant_id):
    """Два филиала одного арендатора, каждый со своим барбером/услугой/
    клиентом/подтверждённой записью на сегодня — минимальный набор, чтобы
    статистика/клиенты/экспорт были непустыми и различимыми по филиалу."""
    marker = uuid.uuid4().hex[:6]
    async with session_factory() as session:
        branch_1 = Branch(tenant_id=tenant_id, name=f"Branch-1-{marker}")
        branch_2 = Branch(tenant_id=tenant_id, name=f"Branch-2-{marker}")
        barber_1 = Barber(tenant_id=tenant_id, name=f"Barber-1-{marker}")
        barber_2 = Barber(tenant_id=tenant_id, name=f"Barber-2-{marker}")
        service = Service(
            tenant_id=tenant_id, name=f"Cut-{marker}", duration_minutes=30, price=Decimal("100")
        )
        user_1 = User(
            tenant_id=tenant_id, telegram_id=910_000_000 + hash(marker) % 100_000,
            full_name="Client One",
        )
        user_2 = User(
            tenant_id=tenant_id, telegram_id=910_100_000 + hash(marker) % 100_000,
            full_name="Client Two",
        )
        session.add_all([branch_1, branch_2, barber_1, barber_2, service, user_1, user_2])
        await session.flush()
        session.add_all([
            BarberBranch(tenant_id=tenant_id, barber_id=barber_1.id, branch_id=branch_1.id),
            BarberBranch(tenant_id=tenant_id, barber_id=barber_2.id, branch_id=branch_2.id),
        ])

        now = now_utc()
        appt_1 = Appointment(
            tenant_id=tenant_id, branch_id=branch_1.id,
            user_id=user_1.id, barber_id=barber_1.id, service_id=service.id,
            starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=1, minutes=30),
            status=AppointmentStatus.CONFIRMED, price=Decimal("100"), duration_minutes=30,
        )
        appt_2 = Appointment(
            tenant_id=tenant_id, branch_id=branch_2.id,
            user_id=user_2.id, barber_id=barber_2.id, service_id=service.id,
            starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=2, minutes=30),
            status=AppointmentStatus.CONFIRMED, price=Decimal("200"), duration_minutes=30,
        )
        session.add_all([appt_1, appt_2])
        await session.commit()
        ids = {
            "branch_1": branch_1.id, "branch_2": branch_2.id,
            "barber_1": barber_1.id, "barber_2": barber_2.id,
            "user_1": user_1.id, "user_2": user_2.id,
            "service": service.id,
        }

    yield ids

    async with session_factory() as session:
        await session.execute(
            delete(Appointment).where(Appointment.tenant_id == tenant_id)
        )
        await session.execute(delete(BarberBranch).where(BarberBranch.tenant_id == tenant_id))
        await session.execute(delete(Barber).where(Barber.tenant_id == tenant_id))
        await session.execute(delete(Service).where(Service.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.execute(delete(Branch).where(Branch.tenant_id == tenant_id))
        await session.commit()


async def _make_manager_restricted_to_branch_1(
    session_factory, tenant_id: uuid.UUID, branch_1_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        manager = await StaffRepository(session, tenant_id).create(
            telegram_id=920_000_000 + uuid.uuid4().int % 100_000, role=Role.MANAGER
        )
        await session.commit()
        manager_id = manager.id
        await BranchRepository(session, tenant_id).assign_staff(
            staff_member_id=manager_id, branch_id=branch_1_id
        )
        await session.commit()
    return manager_id


# --- 1/2. OWNER vs branch-restricted MANAGER: resolve_accessible_branch_ids -
async def test_owner_sees_all_tenant_branches(session_factory, tenant_id, two_branch_shop):
    async with session_factory() as session:
        owner = await StaffRepository(session, tenant_id).create(
            telegram_id=920_100_001, role=Role.TENANT_OWNER
        )
        await session.commit()
        branch_ids = await resolve_accessible_branch_ids(
            session, tenant_id, owner, is_super_admin=False
        )
    assert branch_ids is None  # None = без ограничений
    async with session_factory() as cleanup:
        await cleanup.execute(delete(StaffMember).where(StaffMember.id == owner.id))
        await cleanup.commit()


async def test_branch_restricted_manager_sees_only_assigned_branch(
    session_factory, tenant_id, two_branch_shop
):
    manager_id = await _make_manager_restricted_to_branch_1(
        session_factory, tenant_id, two_branch_shop["branch_1"]
    )
    try:
        async with session_factory() as session:
            manager = await StaffRepository(session, tenant_id).get(manager_id)
            branch_ids = await resolve_accessible_branch_ids(
                session, tenant_id, manager, is_super_admin=False
            )
        assert branch_ids == frozenset({two_branch_shop["branch_1"]})
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(StaffMember).where(StaffMember.id == manager_id))
            await cleanup.commit()


# --- 3. MANAGER cannot see inaccessible branch revenue/stats ----------------
async def test_branch_restricted_manager_stats_exclude_other_branch(
    session_factory, settings, tenant_id, two_branch_shop
):
    async with session_factory() as session:
        stats_unrestricted = await StatsService(session, settings, tenant_id).collect(
            branch_ids=None
        )
        stats_branch_1_only = await StatsService(session, settings, tenant_id).collect(
            branch_ids=frozenset({two_branch_shop["branch_1"]})
        )
    # upcoming/revenue_month, а не today/revenue_today: устойчивы к границе
    # полуночи по локальному времени (см. известный debt H-3, вне scope этой
    # фазы) — starts_at=now+1..2ч всегда "upcoming" и всегда "этот месяц"
    # независимо от времени суток запуска теста. Без ограничений видно обе
    # записи (100 + 200), с ограничением — только запись филиала 1 (100).
    assert stats_unrestricted.upcoming_appointments == 2
    assert stats_unrestricted.revenue_month == pytest.approx(300.0)
    assert stats_branch_1_only.upcoming_appointments == 1
    assert stats_branch_1_only.revenue_month == pytest.approx(100.0)


# --- 4. MANAGER cannot see inaccessible branch customers --------------------
async def test_branch_restricted_manager_client_list_excludes_other_branch_customer(
    session_factory, tenant_id, two_branch_shop
):
    async with session_factory() as session:
        repo = UserRepository(session, tenant_id)
        total_unrestricted = await repo.count(branch_ids=None)
        total_branch_1_only = await repo.count(
            branch_ids=frozenset({two_branch_shop["branch_1"]})
        )
        rows_unrestricted = await repo.list_with_appointment_counts(branch_ids=None)
        rows_branch_1_only = await repo.list_with_appointment_counts(
            branch_ids=frozenset({two_branch_shop["branch_1"]})
        )
    assert total_unrestricted == 2
    assert total_branch_1_only == 1
    ids_branch_1_only = {user.id for user, _count in rows_branch_1_only}
    assert ids_branch_1_only == {two_branch_shop["user_1"]}
    ids_unrestricted = {user.id for user, _count in rows_unrestricted}
    assert ids_unrestricted == {two_branch_shop["user_1"], two_branch_shop["user_2"]}


# --- 5. MANAGER CSV export contains only accessible branch appointments ----
async def test_branch_restricted_manager_csv_export_excludes_other_branch(
    session_factory, settings, tenant_id, two_branch_shop
):
    now = now_utc()
    start = now - timedelta(days=1)
    end = now + timedelta(days=1)
    async with session_factory() as session:
        export = ExportService(session, settings, tenant_id)
        csv_unrestricted = await export.appointments_csv(start=start, end=end, branch_ids=None)
        csv_branch_1_only = await export.appointments_csv(
            start=start, end=end, branch_ids=frozenset({two_branch_shop["branch_1"]})
        )

    rows_unrestricted = list(csv.reader(io.StringIO(csv_unrestricted.decode("utf-8-sig")), delimiter=";"))
    rows_branch_1_only = list(
        csv.reader(io.StringIO(csv_branch_1_only.decode("utf-8-sig")), delimiter=";")
    )
    # Заголовок + N строк.
    assert len(rows_unrestricted) == 3
    assert len(rows_branch_1_only) == 2
    telegram_ids_branch_1_only = {row[7] for row in rows_branch_1_only[1:]}
    async with session_factory() as session:
        user_1 = await session.get(User, two_branch_shop["user_1"])
    assert telegram_ids_branch_1_only == {str(user_1.telegram_id)}


# --- 6. Cross-tenant data remains impossible --------------------------------
async def test_stats_and_export_never_cross_tenant_boundary(
    session_factory, settings, tenant_id, two_branch_shop
):
    other_tenant = Tenant(name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:8]}")
    async with session_factory() as session:
        session.add(other_tenant)
        await session.commit()
        other_tenant_id = other_tenant.id

    try:
        async with session_factory() as session:
            # branch_ids=None (без ограничений) для ДРУГОГО tenant_id не
            # должен видеть ничего из two_branch_shop — tenant_id уже
            # фильтрует на уровне репозитория, branch_ids здесь ни при чём.
            stats_other_tenant = await StatsService(session, settings, other_tenant_id).collect(
                branch_ids=None
            )
            clients_other_tenant = await UserRepository(session, other_tenant_id).count(
                branch_ids=None
            )
        assert stats_other_tenant.today_appointments == 0
        assert stats_other_tenant.revenue_today == pytest.approx(0.0)
        assert clients_other_tenant == 0
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(Tenant).where(Tenant.id == other_tenant_id))
            await cleanup.commit()


async def test_top_services_and_top_barbers_respect_branch_ids(
    session_factory, tenant_id, two_branch_shop
):
    from app.database.repositories import AppointmentRepository

    now = now_utc()
    async with session_factory() as session:
        repo = AppointmentRepository(session, tenant_id)
        top_services_all = await repo.top_services(now=now, branch_ids=None)
        top_services_branch_1 = await repo.top_services(
            now=now, branch_ids=frozenset({two_branch_shop["branch_1"]})
        )
        top_barbers_branch_1 = await repo.top_barbers(
            now=now, branch_ids=frozenset({two_branch_shop["branch_1"]})
        )
    assert sum(count for _name, count, _rev in top_services_all) == 2
    assert sum(count for _name, count, _rev in top_services_branch_1) == 1
    assert sum(count for _name, count, _rev in top_barbers_branch_1) == 1


# === H-3 (Phase 9B): branch-local "today"/"this month", not settings.tz ====
# Etc/GMT+12 (UTC-12, без DST) и Etc/GMT-14 (UTC+14, без DST) — фиксированные
# смещения, заведомо далёкие от settings.tz по умолчанию (Europe/Chisinau,
# UTC+2/+3) и друг от друга (26 часов). now/starts_at подобраны так, чтобы
# ОДИН И ТОТ ЖЕ UTC-момент был "сегодня"/"этот месяц" для одного филиала и
# НЕ был — для другого: это доказывает, что граница вычисляется по Branch.
# timezone для каждой строки, а не по единому процессному часовому поясу.
@pytest.fixture
async def tz_offset_shop(session_factory, tenant_id):
    """Два филиала одного арендатора с фиксированными смещениями, далёкими
    друг от друга и от settings.tz — без барберов/услуг/записей: тесты сами
    создают конкретные Appointment на конкретный UTC-момент."""
    marker = uuid.uuid4().hex[:6]
    async with session_factory() as session:
        branch_plus = Branch(tenant_id=tenant_id, name=f"GMT+12-{marker}", timezone="Etc/GMT+12")
        branch_minus = Branch(
            tenant_id=tenant_id, name=f"GMT-14-{marker}", timezone="Etc/GMT-14"
        )
        # Разные барберы для разных филиалов: exclusion-констрейнт
        # excl_appointments_barber_no_overlap (миграция 0001) не пускает
        # ОДНОГО барбера на пересекающиеся интервалы независимо от филиала,
        # а тесты ниже намеренно ставят записи на один и тот же UTC-момент.
        barber_plus = Barber(tenant_id=tenant_id, name=f"TZBarberPlus-{marker}")
        barber_minus = Barber(tenant_id=tenant_id, name=f"TZBarberMinus-{marker}")
        service = Service(
            tenant_id=tenant_id, name=f"TZCut-{marker}", duration_minutes=30, price=Decimal("100")
        )
        client = User(
            tenant_id=tenant_id, telegram_id=930_000_000 + hash(marker) % 100_000,
            full_name="TZ Client",
        )
        session.add_all([branch_plus, branch_minus, barber_plus, barber_minus, service, client])
        await session.flush()
        session.add_all([
            BarberBranch(tenant_id=tenant_id, barber_id=barber_plus.id, branch_id=branch_plus.id),
            BarberBranch(
                tenant_id=tenant_id, barber_id=barber_minus.id, branch_id=branch_minus.id
            ),
        ])
        await session.commit()
        ids = {
            "branch_plus": branch_plus.id, "branch_minus": branch_minus.id,
            "barber_plus": barber_plus.id, "barber_minus": barber_minus.id,
            "service": service.id, "client": client.id,
        }

    yield ids

    async with session_factory() as session:
        await session.execute(delete(Appointment).where(Appointment.tenant_id == tenant_id))
        await session.execute(delete(BarberBranch).where(BarberBranch.tenant_id == tenant_id))
        await session.execute(delete(Barber).where(Barber.tenant_id == tenant_id))
        await session.execute(delete(Service).where(Service.id == ids["service"]))
        await session.execute(delete(User).where(User.id == ids["client"]))
        await session.execute(delete(Branch).where(Branch.tenant_id == tenant_id))
        await session.commit()


async def _make_appt(session_factory, tenant_id, tz_offset_shop, *, branch_id, starts_at):
    barber_id = (
        tz_offset_shop["barber_plus"]
        if branch_id == tz_offset_shop["branch_plus"]
        else tz_offset_shop["barber_minus"]
    )
    async with session_factory() as session:
        appt = Appointment(
            tenant_id=tenant_id, branch_id=branch_id,
            user_id=tz_offset_shop["client"], barber_id=barber_id,
            service_id=tz_offset_shop["service"],
            starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED, price=Decimal("100"), duration_minutes=30,
        )
        session.add(appt)
        await session.commit()
        return appt.id


async def test_branch_timezone_differs_from_settings_tz(tz_offset_shop, session_factory, tenant_id):
    """Item 1: подтверждаем, что фикстура реально задаёт филиалу timezone,
    отличный от settings.tz (Europe/Chisinau) по умолчанию."""
    async with session_factory() as session:
        branch = await session.get(Branch, tz_offset_shop["branch_plus"])
    assert branch.timezone != "Europe/Chisinau"
    assert branch.timezone == "Etc/GMT+12"


async def test_stats_today_is_branch_local_not_settings_tz(
    session_factory, tenant_id, tz_offset_shop
):
    """Items 2/4/6: один и тот же UTC-момент (2026-06-16T10:00Z) — "сегодня"
    для филиала UTC-12 (2026-06-15 22:00 местного, тот же день, что и "сейчас"
    2026-06-15T12:00Z в этом поясе = 2026-06-15 00:00 местного), но уже
    "завтра" для филиала UTC+14 (2026-06-17 00:00 местного, тогда как
    "сейчас" в этом поясе — 2026-06-16 02:00, т.е. 16 июня)."""
    fixed_now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    shared_instant = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)

    appt_plus_id = await _make_appt(
        session_factory, tenant_id, tz_offset_shop,
        branch_id=tz_offset_shop["branch_plus"], starts_at=shared_instant,
    )
    appt_minus_id = await _make_appt(
        session_factory, tenant_id, tz_offset_shop,
        branch_id=tz_offset_shop["branch_minus"], starts_at=shared_instant,
    )

    try:
        async with session_factory() as session:
            repo = AppointmentRepository(session, tenant_id)
            summary_plus = await repo.summary(
                now=fixed_now, branch_ids=frozenset({tz_offset_shop["branch_plus"]})
            )
            summary_minus = await repo.summary(
                now=fixed_now, branch_ids=frozenset({tz_offset_shop["branch_minus"]})
            )
            summary_all = await repo.summary(now=fixed_now, branch_ids=None)

        # Тот же самый момент: "сегодня" для branch_plus (UTC-12), но не для
        # branch_minus (UTC+14) — граница считается по Branch.timezone
        # каждой строки, а не по единому процессному часовому поясу.
        assert summary_plus["today"] == 1
        assert summary_minus["today"] == 0
        # Агрегат по обоим филиалам не задваивает и не теряет запись.
        assert summary_all["today"] == 1
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(Appointment).where(Appointment.id.in_((appt_plus_id, appt_minus_id)))
            )
            await session.commit()


async def test_stats_month_boundary_is_branch_local(session_factory, tenant_id, tz_offset_shop):
    """Item 3: то же рассуждение, что и для "сегодня", но для границы месяца.
    "Сейчас" = 2026-07-01T00:30Z: для branch_plus (UTC-12) местное время —
    2026-06-30 12:30 (ещё июнь), для branch_minus (UTC+14) — 2026-07-01 14:30
    (уже июль). Запись на 2026-06-29T00:00Z входит в "этот месяц" для
    branch_plus (июнь), но НЕ входит для branch_minus (для него это уже
    прошлый месяц)."""
    fixed_now = datetime(2026, 7, 1, 0, 30, tzinfo=UTC)
    shared_instant = datetime(2026, 6, 29, 0, 0, tzinfo=UTC)

    appt_plus_id = await _make_appt(
        session_factory, tenant_id, tz_offset_shop,
        branch_id=tz_offset_shop["branch_plus"], starts_at=shared_instant,
    )
    appt_minus_id = await _make_appt(
        session_factory, tenant_id, tz_offset_shop,
        branch_id=tz_offset_shop["branch_minus"], starts_at=shared_instant,
    )

    try:
        async with session_factory() as session:
            repo = AppointmentRepository(session, tenant_id)
            summary_plus = await repo.summary(
                now=fixed_now, branch_ids=frozenset({tz_offset_shop["branch_plus"]})
            )
            summary_minus = await repo.summary(
                now=fixed_now, branch_ids=frozenset({tz_offset_shop["branch_minus"]})
            )
        assert summary_plus["month"] == 1
        assert summary_minus["month"] == 0
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(Appointment).where(Appointment.id.in_((appt_plus_id, appt_minus_id)))
            )
            await session.commit()


async def test_export_formats_each_row_in_its_own_branch_timezone(
    session_factory, settings, tenant_id, tz_offset_shop
):
    """Item 5: одна и та же запись (один UTC-момент), привязанная к разным
    филиалам, должна форматироваться в CSV разным локальным временем —
    ровно тем, что даёт Branch.timezone этой конкретной строки."""
    shared_instant = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)
    appt_plus_id = await _make_appt(
        session_factory, tenant_id, tz_offset_shop,
        branch_id=tz_offset_shop["branch_plus"], starts_at=shared_instant,
    )
    appt_minus_id = await _make_appt(
        session_factory, tenant_id, tz_offset_shop,
        branch_id=tz_offset_shop["branch_minus"], starts_at=shared_instant,
    )

    try:
        async with session_factory() as session:
            export = ExportService(session, settings, tenant_id)
            payload = await export.appointments_csv(
                start=shared_instant - timedelta(days=1),
                end=shared_instant + timedelta(days=1),
                branch_ids=None,
            )
        rows = {
            row[0]: (row[1], row[2])
            for row in csv.reader(io.StringIO(payload.decode("utf-8-sig")), delimiter=";")
        }
        # branch_plus — Etc/GMT+12 (UTC-12): 2026-06-16 10:00Z -> 2026-06-15 22:00 местного.
        assert rows[str(appt_plus_id)] == ("2026-06-15", "22:00")
        # branch_minus — Etc/GMT-14 (UTC+14): 2026-06-16 10:00Z -> 2026-06-17 00:00 местного.
        assert rows[str(appt_minus_id)] == ("2026-06-17", "00:00")
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(Appointment).where(Appointment.id.in_((appt_plus_id, appt_minus_id)))
            )
            await session.commit()


async def test_single_branch_stats_and_export_unaffected(
    session_factory, settings, tenant_id, two_branch_shop
):
    """Item 7: существующее однофилиальное (per-branch) поведение не
    изменилось — StatsService.collect() и ExportService по-прежнему
    корректно работают для обычного (settings.tz-совпадающего) филиала."""
    async with session_factory() as session:
        stats = await StatsService(session, settings, tenant_id).collect(
            branch_ids=frozenset({two_branch_shop["branch_1"]})
        )
    assert stats.upcoming_appointments == 1
    assert stats.revenue_month == pytest.approx(100.0)

    async with session_factory() as session:
        export = ExportService(session, settings, tenant_id)
        payload = await export.appointments_csv(
            start=now_utc() - timedelta(days=1),
            end=now_utc() + timedelta(days=3650),
            branch_ids=frozenset({two_branch_shop["branch_1"]}),
        )
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 2  # заголовок + 1 запись
