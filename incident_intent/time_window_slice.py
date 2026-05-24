"""Срез логов по временному окну — единый источник для шагов 1–4."""

from __future__ import annotations

from dataclasses import dataclass, field

from incident_intent.log_filter_models import SourcesCheck, TimeWindowLine
from incident_intent.log_scan import iter_lines_in_time_window


@dataclass
class TimeWindowSlice:
    lines: list[TimeWindowLine] = field(default_factory=list)
    truncated: bool = False
    total_count: int = 0


def build_time_window_slice(
    sources: SourcesCheck,
    time_patterns: tuple[str, ...],
    *,
    max_lines: int | None = None,
) -> TimeWindowSlice:
    """
    Собрать все строки логов, попавшие во временное окно.
    Используется в шагах 1–2; шаги 3–4 работают только с этим срезом.
    """
    lines: list[TimeWindowLine] = []
    total = 0
    truncated = False

    for rel, line_no, text in iter_lines_in_time_window(sources, time_patterns):
        total += 1
        if max_lines is not None and len(lines) >= max_lines:
            truncated = True
            continue
        lines.append(
            TimeWindowLine(
                file=rel,
                line_number=line_no,
                text=text,
            )
        )

    return TimeWindowSlice(lines=lines, truncated=truncated, total_count=total)


def files_in_window(slice_result: TimeWindowSlice) -> list[str]:
    return sorted({line.file for line in slice_result.lines})


def slice_from_request_lines(
    rows: list[TimeWindowLine] | None,
) -> TimeWindowSlice | None:
    if not rows:
        return None
    return TimeWindowSlice(lines=list(rows), truncated=False, total_count=len(rows))
