"""Обход строк логов с фильтром по времени (grep и/или parse)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from incident_intent.log_filter_models import SourcesCheck
from incident_intent.timestamp_parsers import parse_log_timestamp

TimeFilterStrategy = str  # grep | parsed | auto


@dataclass(frozen=True)
class TimeSliceFilter:
    patterns: tuple[str, ...]
    window_start: datetime | None = None
    window_end: datetime | None = None
    strategy: TimeFilterStrategy = "auto"


def line_matches_time(line: str, time_patterns: tuple[str, ...]) -> bool:
    return bool(time_patterns) and any(p in line for p in time_patterns)


def line_in_time_window(
    line: str,
    *,
    file_path: str,
    flt: TimeSliceFilter,
) -> bool:
    if flt.strategy in ("grep", "auto") and line_matches_time(line, flt.patterns):
        return True
    if flt.strategy == "grep":
        return False
    if flt.window_start is None or flt.window_end is None:
        return False
    ts = parse_log_timestamp(line, file_path=file_path)
    if ts is None:
        return False
    return flt.window_start <= ts <= flt.window_end


def resolve_log_path(root: Path, relative_path: str, logs_is_file: bool) -> Path:
    if logs_is_file:
        return root
    return root / relative_path.replace("/", os.sep)


def iter_all_log_lines(
    sources: SourcesCheck,
) -> Iterator[tuple[str, int, str]]:
    if not sources.logs_exists:
        return
    if not sources.logs_is_directory and not sources.logs_is_file:
        return

    root = Path(sources.logs_path).resolve()

    for info in sources.log_files:
        path = resolve_log_path(root, info.relative_path, sources.logs_is_file)
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line_no, raw in enumerate(handle, start=1):
                    yield info.relative_path, line_no, raw.rstrip("\n\r")
        except OSError:
            continue


def iter_lines_in_time_window(
    sources: SourcesCheck,
    flt: TimeSliceFilter,
) -> Iterator[tuple[str, int, str]]:
    if not sources.logs_exists:
        return
    if not sources.logs_is_directory and not sources.logs_is_file:
        return
    if not flt.patterns and flt.strategy == "grep":
        return
    if flt.strategy != "grep" and flt.window_start is None:
        if not flt.patterns:
            return

    root = Path(sources.logs_path).resolve()

    for info in sources.log_files:
        path = resolve_log_path(root, info.relative_path, sources.logs_is_file)
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line_no, raw in enumerate(handle, start=1):
                    if not line_in_time_window(
                        raw,
                        file_path=info.relative_path,
                        flt=flt,
                    ):
                        continue
                    yield info.relative_path, line_no, raw.rstrip("\n\r")
        except OSError:
            continue
