"""Тесты scripts/verify_production_migration.py.

Скрипт живёт вне пакета app (без __init__.py в scripts/), поэтому грузим его
по пути через importlib, а не обычным import — не полагаемся на sys.path.

Часть тестов чисто логическая (без БД). Интеграционная часть — только если
задан TEST_DATABASE_URL (тот же шаблон, что и у остальных интеграционных
тестов, см. tests/test_integration_booking.py) и база реально смигрирована до
головы: она проверяет, что новые 0011/0012/0013-проверки действительно
проходят на настоящей, а не гипотетической схеме.
"""

from __future__ import annotations

import importlib.util
import io
import os
from contextlib import redirect_stdout
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "verify_production_migration.py"
_spec = importlib.util.spec_from_file_location("verify_production_migration", _SCRIPT_PATH)
vpm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vpm)


# --- Логика Check (без БД) --------------------------------------------------


def test_check_defaults_to_fail() -> None:
    """Check создаётся уже как FAIL — забытый .ok()/.warn()/.fail() не
    притворяется PASS-ом молча (требование: не игнорировать ошибки тихо)."""
    check = vpm.Check("something")
    assert check.status == "FAIL"


def test_check_ok_warn_fail_are_distinct() -> None:
    ok = vpm.Check("a")
    ok.ok("detail")
    warn = vpm.Check("b")
    warn.warn("detail")
    fail = vpm.Check("c")
    fail.fail("detail")
    assert (ok.status, warn.status, fail.status) == ("PASS", "WARN", "FAIL")


def test_supported_languages_matches_app_config() -> None:
    """Скрипт сознательно дублирует SUPPORTED_LANGUAGES (не импортирует app,
    см. докстринг скрипта) — эта проверка ловит рассинхронизацию, если
    поддерживаемые языки когда-нибудь изменятся в одном месте и не в другом."""
    from app.config.settings import SUPPORTED_LANGUAGES as APP_SUPPORTED_LANGUAGES

    assert vpm.SUPPORTED_LANGUAGES == APP_SUPPORTED_LANGUAGES


def test_expected_head_is_0013() -> None:
    assert vpm.EXPECTED_HEAD == "0013"


def test_platform_operators_excluded_from_tenant_owned_tables() -> None:
    """platform_operators не арендаторская таблица (нет tenant_id вообще) —
    попадание в этот список сломало бы check_no_orphaned_tenant_ids SQL-ошибкой."""
    assert "platform_operators" not in vpm.TENANT_OWNED_TABLES


def test_telegram_bot_identities_in_tenant_owned_tables() -> None:
    assert "telegram_bot_identities" in vpm.TENANT_OWNED_TABLES


def test_tables_introduced_by_phase_covers_0011_and_0012() -> None:
    covered = {table for tables in vpm.TABLES_INTRODUCED_BY_PHASE.values() for table in tables}
    assert "telegram_bot_identities" in covered
    assert "platform_operators" in covered


# --- Интеграционные проверки против реально смигрированной БД --------------

pytestmark_integration = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL не задан — интеграционные тесты пропущены"
)


@pytest.fixture(scope="module")
def engine(flow_engine):
    return flow_engine


@pytestmark_integration
async def test_alembic_head_check_passes_on_migrated_db(engine) -> None:
    results: list[vpm.Check] = []
    async with engine.connect() as conn:
        await vpm.check_alembic_head(conn, results)
    assert len(results) == 1
    assert results[0].status == "PASS", results[0].detail


@pytestmark_integration
async def test_0011_checks_pass_on_migrated_db(engine) -> None:
    results: list[vpm.Check] = []
    async with engine.connect() as conn:
        await vpm.check_bot_identity_fk(conn, results)
        await vpm.check_bot_identity_unique(conn, results)
        await vpm.check_bot_identity_rows_valid(conn, results)
    failed = [c for c in results if c.status == "FAIL"]
    assert not failed, [(c.name, c.detail) for c in failed]


@pytestmark_integration
async def test_0012_checks_pass_on_migrated_db(engine) -> None:
    results: list[vpm.Check] = []
    async with engine.connect() as conn:
        await vpm.check_platform_operators_unique(conn, results)
        await vpm.check_platform_role_column(conn, results)
        await vpm.check_audit_log_tenant_id_nullable(conn, results)
        await vpm.check_platform_operators_rows_valid(conn, results)
    failed = [c for c in results if c.status == "FAIL"]
    assert not failed, [(c.name, c.detail) for c in failed]


@pytestmark_integration
async def test_0013_checks_pass_on_migrated_db(engine) -> None:
    results: list[vpm.Check] = []
    async with engine.connect() as conn:
        await vpm.check_tenant_language_column(conn, results)
        await vpm.check_staff_language_column(conn, results)
        await vpm.check_tenant_languages_supported(conn, results)
        await vpm.check_staff_languages_supported(conn, results)
    failed = [c for c in results if c.status == "FAIL"]
    assert not failed, [(c.name, c.detail) for c in failed]


async def _row_counts(engine) -> dict[str, int]:
    from sqlalchemy import text

    tables = ("tenants", "staff_members", "audit_log_entries", "telegram_bot_identities",
              "platform_operators", "subscriptions")
    async with engine.connect() as conn:
        return {t: await conn.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables}


@pytestmark_integration
async def test_main_runs_end_to_end_without_modifying_data(engine, monkeypatch) -> None:
    """Полный прогон main() — не проверяет конкретный exit code (эта же БД
    разделяется всей test-сессией; другие файлы намеренно создают/удаляют
    тестовых арендаторов и могут оставить в audit_log_entries строки с
    tenant_id на уже удалённого арендатора — check_no_orphaned_tenant_ids
    корректно это ловит, это не баг скрипта). Здесь проверяется главное
    требование: main() ничего не пишет — счётчики строк совпадают до/после."""
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    before = await _row_counts(engine)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = await vpm.main()
    after = await _row_counts(engine)
    assert exit_code in (0, 1)
    assert before == after, f"main() изменил данные: {before} -> {after}"
