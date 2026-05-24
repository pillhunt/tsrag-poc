"""Классификация ошибок и разбор времени в строках лога."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

ErrorCategory = Literal[
    "sql_deadlock",
    "sql_pk_duplicate",
    "sql_timeout",
    "concurrency",
    "connection",
    "generic_error",
    "other",
]

_RE_TIMESTAMP = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)

_CATEGORY_RULES: list[tuple[ErrorCategory, tuple[str, ...]]] = [
    ("sql_deadlock", ("deadlock", "deadlock victim")),
    ("sql_pk_duplicate", ("PRIMARY KEY", "duplicate key", "PK_BlockLines", "PK_")),
    ("sql_timeout", ("Timeout expired", "timeout expired")),
    ("concurrency", ("карточка изменилась", "сохраните ещё раз", "сохраните еще раз", "изменилась")),
    ("connection", ("ConnectionReset", "connection reset", "оборвал соединение", "разорвано")),
]

_ERROR_MARKERS = (
    "Exception",
    "ERROR",
    "Error",
    "SqlException",
    "DbUpdateException",
    "FAIL",
    "ошибк",
)


def is_global_log_file(relative_path: str) -> bool:
    return "global.log" in relative_path.replace("\\", "/").lower()


def parse_log_timestamp(text: str) -> datetime | None:
    match = _RE_TIMESTAMP.search(text)
    if not match:
        return None
    raw = match.group(1)
    try:
        if "." in raw:
            date_part, frac = raw.split(".", 1)
            frac = (frac + "000000")[:6]
            return datetime.strptime(f"{date_part}.{frac}", "%Y-%m-%d %H:%M:%S.%f")
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def classify_error_line(text: str) -> ErrorCategory | None:
    lower = text.lower()
    for category, markers in _CATEGORY_RULES:
        if any(m.lower() in lower for m in markers):
            return category
    if any(m in text for m in _ERROR_MARKERS):
        return "generic_error"
    return None


def is_error_candidate(text: str, *, global_log_only: bool, is_global: bool) -> bool:
    if global_log_only and not is_global:
        return False
    return classify_error_line(text) is not None


def matched_pattern(text: str, category: ErrorCategory) -> str:
    for cat, markers in _CATEGORY_RULES:
        if cat != category:
            continue
        for m in markers:
            if m.lower() in text.lower():
                return m
    if category == "generic_error":
        for m in _ERROR_MARKERS:
            if m in text:
                return m
    return category
