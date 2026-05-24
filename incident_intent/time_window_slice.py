"""Срез логов по временному окну — единый источник для шагов 1–4."""

from __future__ import annotations

from dataclasses import dataclass, field

from incident_intent.log_filter_models import SourcesCheck, TimeWindowLine
from incident_intent.log_scan import (
    TimeSliceFilter,
    iter_all_log_lines,
    iter_lines_in_time_window,
    line_in_time_window,
)


@dataclass
class TimeWindowSlice:
    lines: list[TimeWindowLine] = field(default_factory=list)
    truncated: bool = False
    total_count: int = 0
    unparsed_skipped: int = 0


def build_time_window_slice(
    sources: SourcesCheck,
    flt: TimeSliceFilter,
    *,
    max_lines: int | None = None,
    full_corpus: bool = False,
) -> TimeWindowSlice:
    if full_corpus:
        line_iter = iter_all_log_lines(sources)
    else:
        line_iter = iter_lines_in_time_window(sources, flt)

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
    main_flt: TimeSliceFilter,
    slow_flt: TimeSliceFilter,
    *,
    max_lines: int | None = None,
    full_corpus: bool = False,
) -> tuple[TimeWindowSlice, TimeWindowSlice]:
    if full_corpus:
        single = build_time_window_slice(sources, main_flt, max_lines=max_lines, full_corpus=True)
        return single, single

    same_filter = (
        main_flt.patterns == slow_flt.patterns
        and main_flt.window_start == slow_flt.window_start
        and main_flt.window_end == slow_flt.window_end
        and main_flt.strategy == slow_flt.strategy
    )
    if same_filter:
        single = build_time_window_slice(sources, main_flt, max_lines=max_lines)
        return single, single

    union_patterns = tuple(dict.fromkeys(main_flt.patterns + slow_flt.patterns))
    starts = [t for t in (main_flt.window_start, slow_flt.window_start) if t is not None]
    ends = [t for t in (main_flt.window_end, slow_flt.window_end) if t is not None]
    union_flt = TimeSliceFilter(
        patterns=union_patterns,
        window_start=min(starts) if starts else None,
        window_end=max(ends) if ends else None,
        strategy=main_flt.strategy,
    )

    main_lines: list[TimeWindowLine] = []
    slow_lines: list[TimeWindowLine] = []
    main_total = 0
    slow_total = 0
    main_trunc = False
    slow_trunc = False

    for rel, line_no, text in iter_lines_in_time_window(sources, union_flt):
        in_main = line_in_time_window(text, file_path=rel, flt=main_flt)
        in_slow = line_in_time_window(text, file_path=rel, flt=slow_flt)
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
