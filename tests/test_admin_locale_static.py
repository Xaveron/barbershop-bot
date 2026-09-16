"""Статический аудит локализации tenant-admin UI (Phase 9F, Task 8/9).

Без БД — чистый AST-анализ исходников. Два независимых чек-листа:

1. Каждый ключ, переданный в t("...") внутри app/bot/handlers/admin/ и
   app/bot/keyboards/admin.py, существует во ВСЕХ трёх каталогах (ru/ro/en).
2. Ни один текстовый литерал в этих файлах не содержит кириллицу, КРОМЕ:
   - docstring модуля/функции/класса (Category E — документация для
     разработчиков, не для пользователя бота);
   - аргументов вызовов logger.<метод>(...) (Category D — внутренние логи,
     никогда не попадают в Telegram);
   - строк, где кириллица встречается только внутри f-string как literal-
     часть, ЕСЛИ вся f-string целиком состоит из уже переведённых кусков
     (эвристика ниже сознательно консервативна — см. _ALLOWED_LITERALS).

Это не заменяет ручной аудит, но ловит регресс: если кто-то в будущем
добавит новый hardcoded русский текст в admin-хендлер, этот тест упадёт.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.bot.i18n import TRANSLATIONS

REPO_ROOT = Path(__file__).resolve().parent.parent
ADMIN_FILES = [
    *sorted((REPO_ROOT / "app/bot/handlers/admin").glob("*.py")),
    REPO_ROOT / "app/bot/keyboards/admin.py",
]

_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]{3,}")

# Проверенные вручную исключения: технические строки, которые ЗАКОНОМЕРНО
# содержат кириллицу вне docstring/logger (например, разделитель-заглушка
# внутри f-string, где реальный текст уже приходит из t()). Пусто, если
# аудит ничего такого не нашёл — оставлено как задел на будущее, а не как
# способ спрятать реальный hardcoded-текст.
_ALLOWED_LITERALS: set[str] = set()


def _iter_t_call_keys(tree: ast.Module) -> list[str]:
    keys: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "t"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.append(node.args[0].value)
    return keys


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """id() младших Constant-узлов, являющихся docstring модуля/функции/класса."""
    ids: set[int] = set()
    candidates: list[ast.AST] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            candidates.append(node)
    for node in candidates:
        doc_node = ast.get_docstring(node, clean=False)
        if doc_node is None:
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            ids.add(id(body[0].value))
    return ids


def _logger_call_arg_ids(tree: ast.Module) -> set[int]:
    """id() строковых констант, переданных как аргументы logger.<method>(...)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant):
                        ids.add(id(sub))
    return ids


def _find_hardcoded_cyrillic(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    doc_ids = _docstring_nodes(tree)
    logger_ids = _logger_call_arg_ids(tree)
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in doc_ids or id(node) in logger_ids:
            continue
        if node.value in _ALLOWED_LITERALS:
            continue
        if _CYRILLIC_RE.search(node.value):
            findings.append(f"{path.name}:{node.lineno}: {node.value!r}")
    return findings


def test_every_t_call_key_exists_in_all_locales():
    missing: list[str] = []
    for path in ADMIN_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for key in _iter_t_call_keys(tree):
            for lang in ("ru", "ro", "en"):
                if key not in TRANSLATIONS[lang]:
                    missing.append(f"{path.name}: missing key {key!r} in locale {lang!r}")
    assert not missing, "\n".join(missing)


def test_no_hardcoded_cyrillic_outside_docstrings_and_logs():
    all_findings: list[str] = []
    for path in ADMIN_FILES:
        all_findings.extend(_find_hardcoded_cyrillic(path))
    assert not all_findings, "\n".join(all_findings)
