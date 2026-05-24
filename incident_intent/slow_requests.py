"""
Шаг 4: долгие HTTP-запросы в срезе строк из шагов 1–2 (любые access-форматы).
"""

from __future__ import annotations

from collections import defaultdict

from incident_intent.http_access_parsers import parse_http_access_line
from incident_intent.keyword_utils import find_matching_keyword, merge_keywords
from incident_intent.slow_request_parser import duration_to_minutes
from incident_intent.slow_requests_models import (
    SlowRequestPathStats,
    SlowRequestRow,
    SlowRequestsRequest,
    SlowRequestsResponse,
)
from incident_intent.time_window_input import require_time_window_slice


def _resolve_http_access_only(req: SlowRequestsRequest) -> bool:
    if req.middleware_only is True:
        return True
    return req.http_access_only


def _build_conclusions(
    rows: list[SlowRequestRow],
    min_ms: int,
    *,
    slice_lines: int,
    scanned_lines: int,
    unparsed: int,
    parsed_by_format: dict[str, int],
) -> list[str]:
    if scanned_lines == 0:
        return [
            f"В срезе шагов 1–2 ({slice_lines} строк) нет строк для анализа HTTP/access.",
            "Проверьте, что в окне времени есть access/middleware/nginx/IIS логи.",
        ]

    if not rows:
        fmt_hint = ", ".join(f"{k}={v}" for k, v in sorted(parsed_by_format.items()))
        extra = f" Распознано по форматам: {fmt_hint}." if fmt_hint else ""
        return [
            f"В срезе ({scanned_lines} строк) нет запросов ≥ {min_ms / 60_000:.0f} мин.{extra}",
            "Снизьте min_duration_ms или расширьте временное окно на шаге 0.",
        ]

    top = rows[0]
    lines = [
        f"Самый долгий (в срезе): {top.method} {top.path} — {top.duration_min} мин, "
        f"метка {top.ended_at or '?'} ({top.log_format or '?'})",
        f"Проанализировано строк в срезе: {scanned_lines} из {slice_lines}.",
        "Следующий шаг — ошибки во всех логах среза (шаг 5).",
    ]
    if unparsed > 0:
        lines.append(f"Строк без распознанного HTTP/access: {unparsed}.")
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

    http_access_only = _resolve_http_access_only(req)
    candidates: list[SlowRequestRow] = []
    parsed_count = 0
    unparsed = 0
    scanned_lines = 0
    access_files: set[str] = set()
    parsed_by_format: dict[str, int] = defaultdict(int)

    for line in time_slice.lines:
        parsed = parse_http_access_line(
            line.text,
            source_file=line.file,
            line_number=line.line_number,
        )
        if parsed is None:
            if not http_access_only:
                unparsed += 1
            continue

        scanned_lines += 1
        access_files.add(line.file)
        parsed_count += 1
        parsed_by_format[parsed.log_format] += 1

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
                source_file=line.file,
                line_number=line.line_number,
                matched_keyword=matched_kw,
                log_format=parsed.log_format,
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
        http_access_only=http_access_only,
        access_files_scanned=sorted(access_files),
        parsed_by_format=dict(parsed_by_format),
        parsed_line_count=parsed_count,
        unparsed_in_window=unparsed,
        slow_requests=slow_rows,
        by_path=by_path[:20],
        conclusions=_build_conclusions(
            slow_rows,
            req.min_duration_ms,
            slice_lines=len(time_slice.lines),
            scanned_lines=scanned_lines,
            unparsed=unparsed,
            parsed_by_format=dict(parsed_by_format),
        ),
        errors=[],
    )
