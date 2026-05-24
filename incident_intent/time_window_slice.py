"""Срез логов по временному окну — единый источник для шагов 1–4."""

from __future__ import annotations

from dataclasses import dataclass, field

from incident_intent.log_filter_models import SourcesCheck, TimeWindowLine
from incident_intent.log_scan import iter_lines_in_time_window, line_matches_time


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
    full_corpus: bool = False,
) -> TimeWindowSlice:
    """
    Собрать строки логов: по времени или весь корпус (full_corpus).
    """
    if full_corpus:
        from incident_intent.log_scan import iter_all_log_lines

        line_iter = iter_all_log_lines(sources)
    else:
        line_iter = iter_lines_in_time_window(sources, time_patterns)

    lines: list[TimeWindowLine] = []
    total = 0
    truncated = False

    for rel, line_no, text in line_iter:
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


def build_dual_time_window_slices(
    sources: SourcesCheck,
    main_patterns: tuple[str, ...],
    slow_patterns: tuple[str, ...],
    *,
    max_lines: int | None = None,
    full_corpus: bool = False,
) -> tuple[TimeWindowSlice, TimeWindowSlice]:
    """Один проход по логам: срез жалобы и расширенный срез для долгих HTTP."""
    if full_corpus:
        single = build_time_window_slice(sources, (), max_lines=max_lines, full_corpus=True)
        return single, single

    if not slow_patterns or slow_patterns == main_patterns:
        single = build_time_window_slice(sources, main_patterns, max_lines=max_lines)
        return single, single

    union = tuple(dict.fromkeys(main_patterns + slow_patterns))
    main_lines: list[TimeWindowLine] = []
    slow_lines: list[TimeWindowLine] = []
    main_total = 0
    slow_total = 0
    main_trunc = False
    slow_trunc = False

    for rel, line_no, text in iter_lines_in_time_window(sources, union):
        in_main = line_matches_time(text, main_patterns)
        in_slow = line_matches_time(text, slow_patterns)
        if in_main:
            main_total += 1
            if max_lines is None or len(main_lines) < max_lines:
                main_lines.append(TimeWindowLine(file=rel, line_number=line_no, text=text))
            else:
                main_trunc = True
        if in_slow:
            slow_total += 1
            if max_lines is None or len(slow_lines) < max_lines:
                slow_lines.append(TimeWindowLine(file=rel, line_number=line_no, text=text))
            else:
                slow_trunc = True

    return (
        TimeWindowSlice(lines=main_lines, truncated=main_trunc, total_count=main_total),
        TimeWindowSlice(lines=slow_lines, truncated=slow_trunc, total_count=slow_total),
    )


def files_in_window(slice_result: TimeWindowSlice) -> list[str]:
    return sorted({line.file for line in slice_result.lines})


def slice_from_request_lines(
    rows: list[TimeWindowLine] | None,
) -> TimeWindowSlice | None:
    if not rows:
        return None
    return TimeWindowSlice(lines=list(rows), truncated=False, total_count=len(rows))
