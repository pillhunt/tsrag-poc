"""
Шаг 5: ошибки в срезе time_window_lines и корреляция с долгими запросами (шаг 4).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from incident_intent.error_classifier import (
    classify_error_line,
    is_global_log_file,
    matched_pattern,
)
from incident_intent.error_correlation_models import (
    CorrelateErrorsRequest,
    CorrelateErrorsResponse,
    ErrorCategoryCount,
    ErrorEngineCount,
    ErrorInWindow,
    SlowRequestCorrelation,
)
from incident_intent.keyword_utils import find_matching_keyword, merge_keywords
from incident_intent.time_window_input import require_time_window_slice
from incident_intent.timestamp_parsers import parse_log_timestamp

_MAX_LINE_LEN = 2000


def _truncate(text: str) -> str:
    if len(text) <= _MAX_LINE_LEN:
        return text
    return text[:_MAX_LINE_LEN] + "…"


def _scope_label(global_log_only: bool) -> str:
    return "только global.log" if global_log_only else "все файлы среза"


def _build_conclusions(
    errors: list[ErrorInWindow],
    correlations: list[SlowRequestCorrelation],
    *,
    unparsed: int,
    slice_size: int,
    global_log_only: bool,
) -> list[str]:
    scope = _scope_label(global_log_only)
    lines: list[str] = []
    if not errors:
        lines.append(
            f"В срезе ({slice_size} строк, {scope}) не найдено ошибок."
        )
        return lines

    by_cat: dict[str, int] = defaultdict(int)
    for e in errors:
        by_cat[e.category] += 1

    top_cats = sorted(by_cat.items(), key=lambda x: -x[1])[:4]
    lines.append(
        "Ошибки в срезе: "
        + ", ".join(f"{cat}={cnt}" for cat, cnt in top_cats)
    )

    with_corr = sum(1 for c in correlations if c.related_errors)
    if correlations:
        lines.append(
            f"К долгим запросам (шаг 4) привязаны ошибки по времени: "
            f"{with_corr} из {len(correlations)}."
        )
        if by_cat.get("sql_pk_duplicate") or by_cat.get("sql_deadlock"):
            lines.append(
                "Возможное объяснение «не с первой попытки»: конфликт в БД "
                "(дубликат ключа, deadlock) при повторной операции."
            )
    elif by_cat.get("sql_timeout") or by_cat.get("pg_statement_timeout"):
        lines.append("Есть таймауты БД — проверьте нагрузку в окне инцидента.")

    if unparsed > 0:
        lines.append(f"У {unparsed} строк ошибок не удалось извлечь время для корреляции.")

    lines.append(
        "Совпадение по времени — сопутствующая связь; для root cause нужен разбор DBA/кода."
    )
    return lines


def correlate_errors(req: CorrelateErrorsRequest) -> CorrelateErrorsResponse:
    time_slice, slice_err = require_time_window_slice(req.time_window_lines)
    if slice_err or time_slice is None:
        return CorrelateErrorsResponse(
            status="error",
            errors=[slice_err or "Нет среза"],
        )

    keywords = merge_keywords(req.search_keywords) if req.filter_by_keywords else []
    if req.filter_by_keywords and not keywords:
        return CorrelateErrorsResponse(
            status="error",
            errors=["filter_by_keywords=true, но search_keywords пуст."],
        )

    errors: list[ErrorInWindow] = []
    unparsed = 0
    category_counts: dict[str, int] = defaultdict(int)
    engine_counts: dict[str, int] = defaultdict(int)

    for line in time_slice.lines:
        is_global = is_global_log_file(line.file)
        if req.global_log_only and not is_global:
            continue

        classified = classify_error_line(line.text, file_path=line.file)
        if classified is None:
            continue
        engine, category = classified

        if keywords and not find_matching_keyword(line.text, keywords):
            continue

        ts = parse_log_timestamp(line.text, file_path=line.file)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:23] if ts else None
        category_counts[category] += 1
        engine_counts[engine] += 1

        if ts is None:
            unparsed += 1

        errors.append(
            ErrorInWindow(
                timestamp=ts_str,
                error_engine=engine,  # type: ignore[arg-type]
                category=category,  # type: ignore[arg-type]
                file=line.file,
                line_number=line.line_number,
                text=_truncate(line.text),
                matched_pattern=matched_pattern(
                    line.text, category, file_path=line.file
                ),
            )
        )

    errors.sort(key=lambda e: (e.timestamp or "", e.file, e.line_number))
    if len(errors) > req.max_errors_returned:
        errors = errors[: req.max_errors_returned]

    by_category = [
        ErrorCategoryCount(category=k, count=v)  # type: ignore[arg-type]
        for k, v in sorted(category_counts.items(), key=lambda x: -x[1])
    ]
    by_engine = [
        ErrorEngineCount(engine=k, count=v)  # type: ignore[arg-type]
        for k, v in sorted(engine_counts.items(), key=lambda x: -x[1])
    ]

    window = timedelta(seconds=req.correlation_window_sec)
    errors_with_ts: list[tuple[ErrorInWindow, datetime]] = []
    for err in errors:
        if err.timestamp:
            parsed = parse_log_timestamp(err.timestamp, file_path=err.file)
            if parsed:
                errors_with_ts.append((err, parsed))

    correlations: list[SlowRequestCorrelation] = []
    for slow in req.slow_requests:
        related: list[ErrorInWindow] = []
        anchor_text = slow.ended_at or ""
        t_end = parse_log_timestamp(anchor_text, file_path=slow.source_file)
        if t_end is None:
            correlations.append(
                SlowRequestCorrelation(slow_request=slow, related_errors=[])
            )
            continue

        t_start = t_end - window
        t_stop = t_end + window
        for err, err_dt in errors_with_ts:
            if t_start <= err_dt <= t_stop:
                related.append(err)
        correlations.append(
            SlowRequestCorrelation(slow_request=slow, related_errors=related)
        )

    return CorrelateErrorsResponse(
        status="ok",
        correlation_window_sec=req.correlation_window_sec,
        global_log_only=req.global_log_only,
        errors_in_window=errors,
        by_category=by_category,
        by_engine=by_engine,
        correlations=correlations,
        unparsed_timestamp_count=unparsed,
        conclusions=_build_conclusions(
            errors,
            correlations,
            unparsed=unparsed,
            slice_size=len(time_slice.lines),
            global_log_only=req.global_log_only,
        ),
        errors=[],
    )
