"""Обход строк логов с фильтром по временным префиксам."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from incident_intent.log_filter_models import SourcesCheck


def line_matches_time(line: str, time_patterns: tuple[str, ...]) -> bool:
    return bool(time_patterns) and any(p in line for p in time_patterns)


def resolve_log_path(root: Path, relative_path: str, logs_is_file: bool) -> Path:
    if logs_is_file:
        return root
    return root / relative_path.replace("/", os.sep)


def iter_lines_in_time_window(
    sources: SourcesCheck,
    time_patterns: tuple[str, ...],
) -> Iterator[tuple[str, int, str]]:
    """Yields (relative_path, line_number, line_text) для строк в окне времени."""
    if not sources.logs_exists:
        return
    if not sources.logs_is_directory and not sources.logs_is_file:
        return
    if not time_patterns:
        return

    root = Path(sources.logs_path).resolve()

    for info in sources.log_files:
        path = resolve_log_path(root, info.relative_path, sources.logs_is_file)
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line_no, raw in enumerate(handle, start=1):
                    if not line_matches_time(raw, time_patterns):
                        continue
                    yield info.relative_path, line_no, raw.rstrip("\n\r")
        except OSError:
            continue
