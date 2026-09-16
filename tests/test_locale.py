"""Юнит-тесты канонического резолвера языка (Phase 9E, app/services/locale.py).

Без БД — resolve_staff_locale/resolve_customer_locale/initial_customer_language
принимают уже прочитанный tenant_default_language как обычную строку.
"""

from __future__ import annotations

import uuid

import pytest

from app.bot.i18n import FALLBACK_LANGUAGE
from app.database.models import Role, StaffMember, User
from app.services.locale import (
    initial_customer_language,
    resolve_customer_locale,
    resolve_staff_locale,
)


def _staff(language: str | None) -> StaffMember:
    return StaffMember(
        tenant_id=uuid.uuid4(), telegram_id=1, role=Role.MANAGER, language=language
    )


def _user(language_code: str | None) -> User:
    return User(
        tenant_id=uuid.uuid4(), telegram_id=1, full_name="Тест", language_code=language_code
    )


# --- 6. Явный язык сотрудника побеждает дефолт арендатора -------------------


def test_staff_explicit_language_wins_over_tenant_default():
    assert resolve_staff_locale(_staff("ro"), tenant_default_language="ru") == "ro"


# --- 7. NULL-язык сотрудника наследует дефолт арендатора --------------------


def test_staff_null_language_inherits_tenant_default():
    assert resolve_staff_locale(_staff(None), tenant_default_language="ro") == "ro"


def test_staff_none_inherits_tenant_default():
    assert resolve_staff_locale(None, tenant_default_language="en") == "en"


# --- 8. Явный язык клиента побеждает дефолт арендатора ----------------------


def test_customer_explicit_language_wins_over_tenant_default():
    assert resolve_customer_locale(_user("en"), tenant_default_language="ru") == "en"


def test_customer_none_language_inherits_tenant_default():
    assert resolve_customer_locale(_user(None), tenant_default_language="ro") == "ro"


# --- 9 (частично). Новый клиент инициализируется поддерживаемым языком
#     Telegram, иначе — дефолтом арендатора ----------------------------------


def test_initial_customer_language_uses_supported_telegram_code():
    assert initial_customer_language("ro", tenant_default_language="ru") == "ro"


def test_initial_customer_language_falls_back_to_tenant_default():
    assert initial_customer_language(None, tenant_default_language="ro") == "ro"


# --- 10. Неподдерживаемый Telegram language_code -> безопасный fallback ----


def test_initial_customer_language_unsupported_code_falls_back():
    assert initial_customer_language("fr-FR", tenant_default_language="ro") == "ro"


@pytest.mark.parametrize("code", ["fr", "de-DE", "", "xx"])
def test_resolve_customer_locale_rejects_unsupported_code(code):
    assert resolve_customer_locale(_user(code or None), tenant_default_language="en") == "en"


# --- 11. Сохранённое предпочтение клиента не перезаписывается живым
#     языком Telegram (сама функция это не делает — она принимает только
#     User.language_code, а не telegram_user.language_code) ------------------


def test_resolve_customer_locale_ignores_live_telegram_language():
    """resolve_customer_locale не принимает telegram_user вообще — только
    уже сохранённый User.language_code. Раз "живой" язык Telegram физически
    не может попасть в эту функцию, он не может и переопределить сохранённое
    предпочтение (гарантия на уровне сигнатуры, а не проверки внутри)."""
    user = _user("ru")
    # Даже если бы у нас был "текущий" telegram_user.language_code="en" —
    # передать его сюда просто негде: сигнатура принимает только User.
    assert resolve_customer_locale(user, tenant_default_language="en") == "ru"


# --- 12. Некорректное сохранённое значение -> безопасный fallback ----------


def test_invalid_stored_staff_language_falls_back_to_tenant_default():
    assert resolve_staff_locale(_staff("xx"), tenant_default_language="ro") == "ro"


def test_invalid_stored_customer_language_falls_back_to_tenant_default():
    assert resolve_customer_locale(_user("xx"), tenant_default_language="ro") == "ro"


def test_invalid_tenant_default_falls_back_to_application_fallback():
    # tenant_default_language сам по себе некорректен (защитный случай —
    # в реальности TenantRepository/normalize_language это предотвращают
    # ещё на записи, но резолвер не должен падать даже на "грязных" данных).
    assert resolve_staff_locale(_staff(None), tenant_default_language="xx") == FALLBACK_LANGUAGE
    assert resolve_customer_locale(_user(None), tenant_default_language="xx") == FALLBACK_LANGUAGE
