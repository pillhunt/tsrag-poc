"""Извлечение даты из имени папки логов (без LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_LOG_FOLDER_DATE = re.compile(
    r"(?:^|[\\/])(?:[A-Za-z0-9._-]+_)?(\d{4}-\d{2}-\d{2})(?:[\\/]|$)"
)


@dataclass(frozen=True)
class LogFolderHint:
    path: str
    iso_date: str | None
    note: str | None


def hint_from_logs_path(logs_path: str | None) -> LogFolderHint | None:
    if not logs_path or not logs_path.strip():
        return None
    normalized = logs_path.strip()
    name = Path(normalized).name
    match = _LOG_FOLDER_DATE.search(normalized) or _LOG_FOLDER_DATE.search(name)
    if not match:
        return LogFolderHint(
            path=normalized,
            iso_date=None,
            note="В пути не найден фрагмент YYYY-MM-DD (как в REN-MSKCASPRO01_2026-04-23).",
        )
    return LogFolderHint(
        path=normalized,
        iso_date=match.group(1),
        note=f"Дата из имени/пути: {match.group(1)}",
    )
