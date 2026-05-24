"""Быстрая оценка диапазона дат в загруженных логах (для подсказок шагов 1–2)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from incident_intent.log_discovery import is_priority_log
from incident_intent.log_filter_models import LogFileInfo
from incident_intent.log_scan import resolve_log_path
from incident_intent.timestamp_parsers import parse_log_timestamp

_MAX_LINES_PER_FILE = 4000
_MAX_FILES = 8


def probe_log_date_range(
    logs_path: str,
    log_files: list[LogFileInfo],
    *,
    logs_is_file: bool,
) -> tuple[date | None, date | None]:
    """
    Мин/макс дата по меткам времени в приоритетных логах (или первых файлах).
    Не сканирует весь каталог — только выборку строк.
    """
    root = Path(logs_path).resolve()
    candidates = [f for f in log_files if f.priority]
    if not candidates:
        candidates = log_files[:_MAX_FILES]
    else:
        candidates = candidates[:_MAX_FILES]

    min_dt: datetime | None = None
    max_dt: datetime | None = None

    for info in candidates:
        path = resolve_log_path(root, info.relative_path, logs_is_file)
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for i, raw in enumerate(handle):
                    if i >= _MAX_LINES_PER_FILE:
                        break
                    ts = parse_log_timestamp(raw, file_path=info.relative_path)
                    if ts is None:
                        continue
                    if min_dt is None or ts < min_dt:
                        min_dt = ts
                    if max_dt is None or ts > max_dt:
                        max_dt = ts
        except OSError:
            continue

    if min_dt is None or max_dt is None:
        return None, None
    return min_dt.date(), max_dt.date()


def format_date_range_hint(
    min_d: date | None,
    max_d: date | None,
    *,
    requested_date: str | None,
) -> str | None:
    if min_d is None or max_d is None:
        return None
    span = f"{min_d.isoformat()} — {max_d.isoformat()}"
    if requested_date and requested_date not in (min_d.isoformat(), max_d.isoformat()):
        if requested_date < min_d.isoformat() or requested_date > max_d.isoformat():
            return (
                f"В приоритетных логах даты {span}, а на шаге 0 указано {requested_date}. "
                "Скорее всего срез пустой из‑за неверной даты — исправьте incident_date и повторите шаги 1–2."
            )
    if min_d != max_d:
        return f"Диапазон дат в логах (выборка): {span}."
    return f"Дата в логах (выборка): {min_d.isoformat()}."
