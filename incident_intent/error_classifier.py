"""Классификация ошибок по правилам error_rules.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

ErrorEngine = Literal[
    "mssql",
    "postgres",
    "nginx",
    "iis",
    "dotnet_app",
    "unknown",
]

ErrorCategory = Literal[
    "sql_deadlock",
    "sql_pk_duplicate",
    "sql_timeout",
    "sql_connection",
    "pg_deadlock",
    "pg_unique_violation",
    "pg_statement_timeout",
    "pg_connection",
    "nginx_upstream_timeout",
    "nginx_connect_refused",
    "nginx_ssl",
    "iis_500",
    "iis_timeout",
    "iis_502_503",
    "concurrency",
    "connection",
    "generic_error",
    "other",
]

_RULES_FILE = Path(__file__).resolve().parent / "error_rules.yaml"


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    if not _RULES_FILE.is_file():
        raise FileNotFoundError(f"Не найден файл правил: {_RULES_FILE}")
    data = yaml.safe_load(_RULES_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def infer_log_kind(relative_path: str) -> str:
    """app | web | db | unknown — эвристика по пути файла."""
    engine = infer_error_engine(relative_path, "")
    if engine in ("mssql", "postgres"):
        return "db"
    if engine in ("nginx", "iis"):
        return "web"
    if engine == "dotnet_app":
        return "app"
    return "unknown"


def infer_error_engine(relative_path: str, text: str) -> ErrorEngine:
    path_lower = relative_path.replace("\\", "/").lower()
    rules = _load_rules()
    engines: dict[str, Any] = rules.get("engines") or {}

    for name, spec in engines.items():
        hints = spec.get("file_hints") or []
        if any(h.lower() in path_lower for h in hints):
            return name  # type: ignore[return-value]

    text_lower = text.lower()
    if any(x in text_lower for x in ("sql exception", "sqlexception", "dbupdate")):
        return "dotnet_app"
    if "postgresql" in text_lower or "pg::" in text_lower:
        return "postgres"
    return "unknown"


def classify_error_line(
    text: str,
    *,
    file_path: str = "",
) -> tuple[ErrorEngine, ErrorCategory] | None:
    rules = _load_rules()
    engines: dict[str, Any] = rules.get("engines") or {}
    engine = infer_error_engine(file_path, text)

    search_order: list[str] = []
    if engine != "unknown" and engine in engines:
        search_order.append(engine)
    for name in engines:
        if name not in search_order:
            search_order.append(name)

    lower = text.lower()
    for eng_name in search_order:
        spec = engines.get(eng_name) or {}
        categories: dict[str, Any] = spec.get("categories") or {}
        for cat_name, cat_spec in categories.items():
            markers = cat_spec.get("markers") or []
            if any(m.lower() in lower for m in markers):
                return eng_name, cat_name  # type: ignore[return-value]

    generic = rules.get("generic") or {}
    generic_markers = generic.get("markers") or []
    if any(m in text or m.lower() in lower for m in generic_markers):
        cat = generic.get("category") or "generic_error"
        return engine if engine != "unknown" else "unknown", cat  # type: ignore[return-value]

    return None


def is_global_log_file(relative_path: str) -> bool:
    return "global.log" in relative_path.replace("\\", "/").lower()


def is_error_candidate(
    text: str,
    *,
    global_log_only: bool,
    is_global: bool,
    file_path: str = "",
) -> bool:
    if global_log_only and not is_global:
        return False
    return classify_error_line(text, file_path=file_path) is not None


def matched_pattern(text: str, category: str, *, file_path: str = "") -> str:
    rules = _load_rules()
    engines: dict[str, Any] = rules.get("engines") or {}
    lower = text.lower()

    for spec in engines.values():
        categories: dict[str, Any] = spec.get("categories") or {}
        cat_spec = categories.get(category)
        if not cat_spec:
            continue
        for marker in cat_spec.get("markers") or []:
            if marker.lower() in lower:
                return marker

    generic = rules.get("generic") or {}
    if category == generic.get("category"):
        for marker in generic.get("markers") or []:
            if marker in text or marker.lower() in lower:
                return marker

    del file_path
    return category
