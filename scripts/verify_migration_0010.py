"""Read-only проверка состояния БД после миграции 0010 (Phase 6.5).

Запуск:
    export DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
    python scripts/verify_migration_0010.py

Ничего не пишет и не меняет — только SELECT-ы. Годится и для scratch-БД,
и для восстановленной копии production, но НИКОГДА не должен указывать на
настоящую production-базу без явного, осознанного решения оператора (см.
docs/PRODUCTION_MIGRATION_RUNBOOK.md).

Не привязан к моделям SQLAlchemy: только сырой SQL по системным каталогам
Postgres и таблицам приложения — минимальная зависимость, максимум
уверенности, что проверка видит именно то, что реально лежит в базе, а не то,
что думает про себя ORM.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

EXPECTED_HEAD = "0010"

# Таблицы, появившиеся в 0004-0010 — если какой-то из них нет, миграция
# явно не докатилась до головы.
TABLES_INTRODUCED_BY_PHASE = {
    "0004 (tenants)": ["tenants"],
    "0005 (RBAC)": ["staff_members"],
    "0006 (audit log)": ["audit_log_entries"],
    "0007 (branches)": ["branches", "barber_branches", "branch_services", "staff_branches"],
    "0008 (barber_services)": ["barber_services"],
    "0010 (billing)": ["plans", "plan_features", "plan_limits", "subscriptions"],
}

TENANT_OWNED_TABLES = (
    "users",
    "barbers",
    "services",
    "working_schedules",
    "schedule_exceptions",
    "appointments",
    "staff_members",
    "audit_log_entries",
    "branches",
    "barber_branches",
    "branch_services",
    "staff_branches",
    "barber_services",
    "subscriptions",
)

# (child table, child FK column, parent table, parent's own tenant_id join)
# — проверяем, что связка child->parent никогда не пересекает арендаторов.
CROSS_TENANT_LINKS = [
    ("barber_branches", "barber_id", "barbers"),
    ("barber_branches", "branch_id", "branches"),
    ("branch_services", "branch_id", "branches"),
    ("branch_services", "service_id", "services"),
    ("staff_branches", "staff_member_id", "staff_members"),
    ("staff_branches", "branch_id", "branches"),
    ("barber_services", "barber_id", "barbers"),
    ("barber_services", "service_id", "services"),
]


class Check:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = False
        self.detail = ""

    def ok(self, detail: str = "") -> None:
        self.passed = True
        self.detail = detail

    def fail(self, detail: str) -> None:
        self.passed = False
        self.detail = detail


async def check_alembic_head(conn, results: list[Check]) -> None:
    check = Check("alembic_version is at head (0010)")
    try:
        rows = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    except Exception as exc:
        check.fail(f"не удалось прочитать alembic_version: {exc}")
        results.append(check)
        return
    if rows == [EXPECTED_HEAD]:
        check.ok(f"version_num={rows[0]}")
    else:
        check.fail(f"ожидали ровно одну строку '{EXPECTED_HEAD}', получили {rows}")
    results.append(check)


async def check_tables_exist(conn, results: list[Check]) -> None:
    existing = set(
        (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        )
        .scalars()
        .all()
    )
    for phase, tables in TABLES_INTRODUCED_BY_PHASE.items():
        check = Check(f"tables from {phase} exist")
        missing = [t for t in tables if t not in existing]
        if missing:
            check.fail(f"отсутствуют: {missing}")
        else:
            check.ok(f"{tables}")
        results.append(check)


async def check_exclude_constraint(conn, results: list[Check]) -> None:
    check = Check("excl_appointments_barber_no_overlap existует (EXCLUDE constraint)")
    row = await conn.scalar(
        text(
            "SELECT 1 FROM pg_constraint WHERE conname = "
            "'excl_appointments_barber_no_overlap' AND contype = 'x'"
        )
    )
    if row:
        check.ok()
    else:
        check.fail("constraint не найден — защита от двойного бронирования под угрозой")
    results.append(check)


async def check_owner_uniqueness_index(conn, results: list[Check]) -> None:
    check = Check("uq_staff_members_tenant_id_owner существует (partial unique index)")
    row = await conn.scalar(
        text(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_staff_members_tenant_id_owner' "
            "AND tablename = 'staff_members'"
        )
    )
    if row:
        check.ok()
    else:
        check.fail("индекс не найден — два tenant_owner на арендатора технически возможны")
    results.append(check)


async def check_billing_backfill_complete(conn, results: list[Check]) -> None:
    check = Check("у каждого tenant ровно одна subscription")
    total_tenants = await conn.scalar(text("SELECT count(*) FROM tenants"))
    tenants_without = await conn.scalar(
        text(
            "SELECT count(*) FROM tenants t "
            "WHERE NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.tenant_id = t.id)"
        )
    )
    duplicate_subs = await conn.scalar(
        text(
            "SELECT count(*) FROM ("
            "  SELECT tenant_id FROM subscriptions GROUP BY tenant_id HAVING count(*) > 1"
            ") d"
        )
    )
    if tenants_without == 0 and duplicate_subs == 0:
        check.ok(f"{total_tenants} tenant(s), все с ровно одной подпиской")
    else:
        check.fail(f"без подписки: {tenants_without}, с дублями подписки: {duplicate_subs}")
    results.append(check)


async def check_subscription_plans_valid(conn, results: list[Check]) -> None:
    check = Check("каждая subscription ссылается на известный тариф (free/pro/legacy)")
    bad = await conn.scalar(
        text(
            "SELECT count(*) FROM subscriptions s "
            "JOIN plans p ON p.id = s.plan_id "
            "WHERE p.code NOT IN ('free', 'pro', 'legacy')"
        )
    )
    orphaned = await conn.scalar(
        text(
            "SELECT count(*) FROM subscriptions s "
            "WHERE NOT EXISTS (SELECT 1 FROM plans p WHERE p.id = s.plan_id)"
        )
    )
    if bad == 0 and orphaned == 0:
        check.ok()
    else:
        check.fail(f"неизвестный код тарифа: {bad}, ссылка на несуществующий план: {orphaned}")
    results.append(check)


async def check_no_cross_tenant_leakage(conn, results: list[Check]) -> None:
    for child_table, fk_column, parent_table in CROSS_TENANT_LINKS:
        check = Check(f"{child_table}.{fk_column} -> {parent_table}: tenant_id совпадает")
        # Имена таблиц/колонок берутся из фиксированного списка CROSS_TENANT_LINKS
        # выше, не из пользовательского ввода.
        mismatched = await conn.scalar(
            text(
                f"SELECT count(*) FROM {child_table} c "
                f"JOIN {parent_table} p ON p.id = c.{fk_column} "
                f"WHERE c.tenant_id != p.tenant_id"
            )
        )
        if mismatched == 0:
            check.ok()
        else:
            check.fail(f"{mismatched} строк(и) с чужим tenant_id — утечка между арендаторами")
        results.append(check)


async def check_no_orphaned_tenant_ids(conn, results: list[Check]) -> None:
    for table in TENANT_OWNED_TABLES:
        check = Check(f"{table}.tenant_id: нет ссылок на несуществующего арендатора")
        # Имя таблицы берётся из фиксированного списка TENANT_OWNED_TABLES выше.
        orphaned = await conn.scalar(
            text(
                f"SELECT count(*) FROM {table} t "
                f"WHERE NOT EXISTS (SELECT 1 FROM tenants te WHERE te.id = t.tenant_id)"
            )
        )
        if orphaned == 0:
            check.ok()
        else:
            check.fail(f"{orphaned} строк(и) с tenant_id, которого нет в tenants")
        results.append(check)


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL не задан — укажите БД для проверки явно.", file=sys.stderr)
        return 2

    # Не полагаемся на молчаливые дефолты Settings: явная переменная окружения
    # — единственный источник, чтобы случайно не проверить не ту базу.
    engine = create_async_engine(database_url)
    results: list[Check] = []
    try:
        async with engine.connect() as conn:
            await check_alembic_head(conn, results)
            await check_tables_exist(conn, results)
            await check_exclude_constraint(conn, results)
            await check_owner_uniqueness_index(conn, results)
            await check_billing_backfill_complete(conn, results)
            await check_subscription_plans_valid(conn, results)
            await check_no_cross_tenant_leakage(conn, results)
            await check_no_orphaned_tenant_ids(conn, results)
    finally:
        await engine.dispose()

    failed = [c for c in results if not c.passed]
    for c in results:
        mark = "PASS" if c.passed else "FAIL"
        suffix = f" — {c.detail}" if c.detail else ""
        print(f"[{mark}] {c.name}{suffix}")

    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
