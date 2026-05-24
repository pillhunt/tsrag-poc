"""
Шаг 4: долгие HTTP-запросы только в срезе строк из шагов 1–2 (middleware).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from incident_intent.keyword_utils import find_matching_keyword, merge_keywords
from incident_intent.slow_request_parser import (
    duration_to_minutes,
    is_middleware_log,
    parse_request_line,
)
from incident_intent.slow_requests_models import (
    SlowRequestPathStats,
    SlowRequestRow,
    SlowRequestsRequest,
    SlowRequestsResponse,
)
from incident_intent.time_window_input import require_time_window_slice


def _build_conclusions(
    rows: list[SlowRequestRow],
    min_ms: int,
    *,
    slice_lines: int,
    middleware_lines: int,
    unparsed: int,
) -> list[str]:
    if middleware_lines == 0:
        return [
            f"В срезе шагов 1–2 ({slice_lines} строк) нет строк из RequestLoggingMiddleware.",
            "Проверьте, что в окне времени есть записи middleware-лога.",
        ]

    if not rows:
        return [
            f"В срезе middleware ({middleware_lines} строк) нет запросов ≥ {min_ms / 60_000:.0f} мин.",
            "Снизьте min_duration_ms или расширьте временное окно на шаге 0.",
        ]

    top = rows[0]
    lines = [
        f"Самый долгий (в срезе): {top.method} {top.path} — {top.duration_min} мин, "
        f"метка {top.ended_at or '?'}",
        f"Проанализировано строк middleware в срезе: {middleware_lines} из {slice_lines}.",
        "Следующий шаг — ошибки в global.log на время окончания (шаг 5).",
    ]
    if unparsed > 0:
        lines.append(f"Не разобрано строк middleware в срезе: {unparsed}.")
    return lines


def find_slow_requests(req: SlowRequestsRequest) -> SlowRequestsResponse:
    time_slice, slice_err = require_time_window_slice(req.time_window_lines)
    if slice_err or time_slice is None:
        return SlowRequestsResponse(
            status="error",
            errors=[slice_err or "Нет среза"],
        )

    keywords = merge_keywords(req.search_keywords) if req.filter_by_keywords else []
    if req.filter_by_keywords and not keywords:
        return SlowRequestsResponse(
            status="error",
            errors=["filter_by_keywords=true, но search_keywords пуст."],
        )

    candidates: list[SlowRequestRow] = []
    parsed_count = 0
    unparsed = 0
    middleware_lines = 0
    middleware_files: set[str] = set()

    for line in time_slice.lines:
        if req.middleware_only and not is_middleware_log(line.file):
            continue
        middleware_lines += 1
        middleware_files.add(line.file)

        parsed = parse_request_line(
            line.text,
            source_file=line.file,
            line_number=line.line_number,
        )
        if parsed is None:
            unparsed += 1
            continue
        parsed_count += 1

        if parsed.duration_ms < req.min_duration_ms:
            continue

        matched_kw = (
            find_matching_keyword(f"{parsed.path} {line.text}", keywords)
            if keywords
            else None
        )
        if keywords and matched_kw is None:
            continue

        candidates.append(
            SlowRequestRow(
                ended_at=parsed.ended_at,
                method=parsed.method,
                path=parsed.path,
                duration_ms=parsed.duration_ms,
                duration_min=duration_to_minutes(parsed.duration_ms),
                source_file=parsed.source_file,
                line_number=parsed.line_number,
                matched_keyword=matched_kw,
            )
        )

    candidates.sort(key=lambda r: (-r.duration_ms, r.ended_at or "", r.path))
    slow_rows = candidates[: req.top_n]

    path_agg: dict[str, list[int]] = defaultdict(list)
    for row in candidates:
        path_agg[row.path].append(row.duration_ms)

    by_path = [
        SlowRequestPathStats(
            path=path,
            count=len(durations),
            max_duration_ms=max(durations),
            max_duration_min=duration_to_minutes(max(durations)),
            avg_duration_ms=int(sum(durations) / len(durations)),
        )
        for path, durations in path_agg.items()
    ]
    by_path.sort(key=lambda x: (-x.max_duration_ms, -x.count, x.path))

    return SlowRequestsResponse(
        status="ok",
        time_patterns_used=req.log_search_patterns,
        min_duration_ms=req.min_duration_ms,
        filter_by_keywords=req.filter_by_keywords,
        middleware_files_scanned=sorted(middleware_files),
        parsed_line_count=parsed_count,
        unparsed_in_window=unparsed,
        slow_requests=slow_rows,
        by_path=by_path[:20],
        conclusions=_build_conclusions(
            slow_rows,
            req.min_duration_ms,
            slice_lines=len(time_slice.lines),
            middleware_lines=middleware_lines,
            unparsed=unparsed,
        ),
        errors=[],
    )
