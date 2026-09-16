"""Read-only проверка состояния БД после миграции до текущей головы (0013).

Запуск:
    export DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
    python scripts/verify_production_migration.py

Ничего не пишет и не меняет — только SELECT-ы. Годится и для scratch-БД,
и для восстановленной копии production, но НИКОГДА не должен указывать на
настоящую production-базу без явного, осознанного решения оператора (см.
docs/PRODUCTION_MIGRATION_RUNBOOK.md).

Не привязан к моделям SQLAlchemy: только сырой SQL по системным каталогам
Postgres и таблицам приложения — минимальная зависимость, максимум
уверенности, что проверка видит именно то, что реально лежит в базе, а не то,
что думает про себя ORM.

Заменяет scripts/verify_migration_0010.py (Phase 6.5) — та версия знала
только про миграции 0004-0010. Эта версия добавляет 0011 (bot identities),
0012 (platform operators) и 0013 (языковые колонки), не теряя ни одной из
исходных проверок.

Три уровня результата на каждую проверку:
    PASS — всё как ожидается.
    WARN — не ошибка, но заслуживает внимания оператора (например, таблица
           существует и структурно верна, но пуста — до python -m
           app.register_bot / app.bootstrap_platform_admin это ожидаемо).
    FAIL — реальная проблема, скрипт завершится ненулевым кодом.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import create_async_engine

EXPECTED_HEAD = "0013"

# Дублирует app.config.settings.SUPPORTED_LANGUAGES намеренно — этот скрипт
# сознательно не импортирует ORM/приложение (см. докстринг выше), ровно та же
# причина, по которой settings.py сам дублирует список у app.bot.i18n.
SUPPORTED_LANGUAGES = ("ru", "ro", "en")

# Таблицы, появившиеся в 0004-0013 — если какой-то из них нет, миграция
# явно не докатилась до головы.
TABLES_INTRODUCED_BY_PHASE = {
    "0004 (tenants)": ["tenants"],
    "0005 (RBAC)": ["staff_members"],
    "0006 (audit log)": ["audit_log_entries"],
    "0007 (branches)": ["branches", "barber_branches", "branch_services", "staff_branches"],
    "0008 (barber_services)": ["barber_services"],
    "0010 (billing)": ["plans", "plan_features", "plan_limits", "subscriptions"],
    "0011 (bot identities)": ["telegram_bot_identities"],
    "0012 (platform operators)": ["platform_operators"],
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
    "telegram_bot_identities",
)

# (child table, child FK column, parent table, parent's own tenant_id join)
# — проверяем, что связка child->parent никогда не пересекает арендаторов.
# platform_operators намеренно не участвует нигде в этом списке — у него нет
# tenant_id вообще, это глобальный, не арендаторский каталог (см. §Platform
# identity в docs/PLATFORM_CONTROL_PLANE.md).
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
        self.status = "FAIL"
        self.detail = ""

    def ok(self, detail: str = "") -> None:
        self.status = "PASS"
        self.detail = detail

    def warn(self, detail: str) -> None:
        self.status = "WARN"
        self.detail = detail

    def fail(self, detail: str) -> None:
        self.status = "FAIL"
        self.detail = detail


async def _column_info(conn, table: str, column: str) -> dict | None:
    """information_schema-справка по одной колонке: is_nullable/udt_name, либо
    None, если колонки (или таблицы) нет. table/column — только из фиксированных
    констант этого файла, никогда из внешнего ввода."""
    row = (
        await conn.execute(
            text(
                "SELECT is_nullable, udt_name FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
    ).mappings().first()
    return dict(row) if row is not None else None


# --- Существующие проверки (унаследованы из verify_migration_0010.py) ------


async def check_alembic_head(conn, results: list[Check]) -> None:
    check = Check(f"alembic_version is at head ({EXPECTED_HEAD})")
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
    check = Check("excl_appointments_barber_no_overlap существует (EXCLUDE constraint)")
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


# --- Новые проверки: 0011 (telegram_bot_identities) ------------------------


async def check_bot_identity_fk(conn, results: list[Check]) -> None:
    check = Check("telegram_bot_identities.tenant_id: FK на tenants существует")
    row = await conn.scalar(
        text(
            "SELECT 1 FROM pg_constraint WHERE "
            "conname = 'fk_telegram_bot_identities_tenant_id_tenants' AND contype = 'f'"
        )
    )
    if row:
        check.ok()
    else:
        check.fail("внешний ключ не найден")
    results.append(check)


async def check_bot_identity_unique(conn, results: list[Check]) -> None:
    check = Check("telegram_bot_identities.telegram_bot_id: глобально уникален")
    constraint = await conn.scalar(
        text(
            "SELECT 1 FROM pg_constraint WHERE "
            "conname = 'uq_telegram_bot_identities_telegram_bot_id' AND contype = 'u'"
        )
    )
    duplicates = await conn.scalar(
        text(
            "SELECT count(*) FROM ("
            "  SELECT telegram_bot_id FROM telegram_bot_identities "
            "  GROUP BY telegram_bot_id HAVING count(*) > 1"
            ") d"
        )
    )
    if constraint and duplicates == 0:
        check.ok()
    elif not constraint:
        check.fail("unique constraint не найден в схеме")
    else:
        check.fail(f"{duplicates} значений telegram_bot_id встречаются более одного раза")
    results.append(check)


async def check_bot_identity_rows_valid(conn, results: list[Check]) -> None:
    check = Check("telegram_bot_identities: строки структурно валидны")
    total = await conn.scalar(text("SELECT count(*) FROM telegram_bot_identities"))
    invalid = await conn.scalar(
        text(
            "SELECT count(*) FROM telegram_bot_identities "
            "WHERE telegram_bot_id IS NULL OR tenant_id IS NULL OR is_active IS NULL"
        )
    )
    if invalid:
        check.fail(f"{invalid} строк(и) с NULL в telegram_bot_id/tenant_id/is_active")
    elif total == 0:
        check.warn("таблица пуста — ни один бот ещё не привязан (см. python -m app.register_bot)")
    else:
        active = await conn.scalar(
            text("SELECT count(*) FROM telegram_bot_identities WHERE is_active")
        )
        check.ok(f"{total} строк(и), активных: {active}")
    results.append(check)


# --- Новые проверки: 0012 (platform_operators, audit_log_entries) ----------


async def check_platform_operators_unique(conn, results: list[Check]) -> None:
    check = Check("platform_operators.telegram_user_id: уникален")
    constraint = await conn.scalar(
        text(
            "SELECT 1 FROM pg_constraint WHERE "
            "conname = 'uq_platform_operators_telegram_user_id' AND contype = 'u'"
        )
    )
    duplicates = await conn.scalar(
        text(
            "SELECT count(*) FROM ("
            "  SELECT telegram_user_id FROM platform_operators "
            "  GROUP BY telegram_user_id HAVING count(*) > 1"
            ") d"
        )
    )
    if constraint and duplicates == 0:
        check.ok()
    elif not constraint:
        check.fail("unique constraint не найден в схеме")
    else:
        check.fail(f"{duplicates} значений telegram_user_id встречаются более одного раза")
    results.append(check)


async def check_platform_role_column(conn, results: list[Check]) -> None:
    check = Check("platform_operators.role: колонка существует (тип platform_role)")
    info = await _column_info(conn, "platform_operators", "role")
    if info is None:
        check.fail("колонка не найдена")
    elif info["udt_name"] != "platform_role":
        check.fail(f"неожиданный тип: {info['udt_name']}")
    else:
        check.ok()
    results.append(check)


async def check_audit_log_tenant_id_nullable(conn, results: list[Check]) -> None:
    check = Check("audit_log_entries.tenant_id: nullable (платформенные события без арендатора)")
    info = await _column_info(conn, "audit_log_entries", "tenant_id")
    if info is None:
        check.fail("колонка не найдена")
    elif info["is_nullable"] != "YES":
        check.fail("колонка всё ещё NOT NULL — миграция 0012 не применена или откачена")
    else:
        check.ok()
    results.append(check)


async def check_platform_operators_rows_valid(conn, results: list[Check]) -> None:
    check = Check("platform_operators: строки структурно валидны")
    total = await conn.scalar(text("SELECT count(*) FROM platform_operators"))
    invalid = await conn.scalar(
        text(
            "SELECT count(*) FROM platform_operators "
            "WHERE telegram_user_id IS NULL OR role IS NULL OR is_active IS NULL"
        )
    )
    if invalid:
        check.fail(f"{invalid} строк(и) с NULL в telegram_user_id/role/is_active")
    elif total == 0:
        check.warn(
            "таблица пуста — ни один platform operator не создан "
            "(см. python -m app.bootstrap_platform_admin)"
        )
    else:
        active = await conn.scalar(text("SELECT count(*) FROM platform_operators WHERE is_active"))
        check.ok(f"{total} строк(и), активных: {active}")
    results.append(check)


# --- Новые проверки: 0013 (языковые колонки) --------------------------------


async def check_tenant_language_column(conn, results: list[Check]) -> None:
    check = Check("tenants.default_language: колонка существует и NOT NULL")
    info = await _column_info(conn, "tenants", "default_language")
    if info is None:
        check.fail("колонка не найдена")
    elif info["is_nullable"] != "NO":
        check.fail("колонка nullable — ожидали NOT NULL после бэкфилла миграции 0013")
    else:
        check.ok()
    results.append(check)


async def check_staff_language_column(conn, results: list[Check]) -> None:
    check = Check("staff_members.language: колонка существует и nullable")
    info = await _column_info(conn, "staff_members", "language")
    if info is None:
        check.fail("колонка не найдена")
    elif info["is_nullable"] != "YES":
        check.fail("колонка NOT NULL — ожидали nullable (NULL = наследует Tenant.default_language)")
    else:
        check.ok()
    results.append(check)


async def check_tenant_languages_supported(conn, results: list[Check]) -> None:
    check = Check("tenants.default_language: только поддерживаемые значения")
    stmt = text(
        "SELECT DISTINCT default_language FROM tenants WHERE default_language NOT IN :langs"
    ).bindparams(bindparam("langs", expanding=True))
    bad = (await conn.execute(stmt, {"langs": list(SUPPORTED_LANGUAGES)})).scalars().all()
    if bad:
        check.fail(f"неподдерживаемые значения: {bad} (ожидали одно из {SUPPORTED_LANGUAGES})")
    else:
        check.ok()
    results.append(check)


async def check_staff_languages_supported(conn, results: list[Check]) -> None:
    check = Check("staff_members.language: только поддерживаемые значения (или NULL)")
    stmt = text(
        "SELECT DISTINCT language FROM staff_members "
        "WHERE language IS NOT NULL AND language NOT IN :langs"
    ).bindparams(bindparam("langs", expanding=True))
    bad = (await conn.execute(stmt, {"langs": list(SUPPORTED_LANGUAGES)})).scalars().all()
    if bad:
        check.fail(f"неподдерживаемые значения: {bad} (ожидали одно из {SUPPORTED_LANGUAGES})")
    else:
        check.ok()
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
            await check_bot_identity_fk(conn, results)
            await check_bot_identity_unique(conn, results)
            await check_bot_identity_rows_valid(conn, results)
            await check_platform_operators_unique(conn, results)
            await check_platform_role_column(conn, results)
            await check_audit_log_tenant_id_nullable(conn, results)
            await check_platform_operators_rows_valid(conn, results)
            await check_tenant_language_column(conn, results)
            await check_staff_language_column(conn, results)
            await check_tenant_languages_supported(conn, results)
            await check_staff_languages_supported(conn, results)
    finally:
        await engine.dispose()

    for c in results:
        suffix = f" — {c.detail}" if c.detail else ""
        print(f"[{c.status}] {c.name}{suffix}")

    failed = [c for c in results if c.status == "FAIL"]
    warned = [c for c in results if c.status == "WARN"]
    passed = [c for c in results if c.status == "PASS"]
    print(
        f"\n{len(passed)}/{len(results)} passed, {len(warned)} warning(s), "
        f"{len(failed)} failed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
