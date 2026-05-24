"""
Шаги 1–2 разбора инцидента: проверка путей и срез логов по префиксам времени.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from incident_intent.log_discovery import discover_log_files, is_priority_log, log_kind_for_path
from incident_intent.path_resolve import (
    is_docker_runtime,
    path_hints_for_missing,
    resolve_host_path,
)
from incident_intent.log_filter_models import (
    FileMatchStats,
    FilterLogsRequest,
    FilterLogsResponse,
    LogFileInfo,
    SampleLine,
    SourcesCheck,
    TimeWindowLine,
)
from incident_intent.log_scan import TimeSliceFilter
from incident_intent.time_pattern_factory import enrich_log_search_patterns
from incident_intent.time_window_bounds import datetime_window_bounds
from incident_intent.time_window_slice import (
    build_dual_time_window_slices,
    files_in_window,
)
from incident_intent.time_window_utils import DEFAULT_SLOW_PADDING_H, expand_time_window_hours
from incident_intent.timestamp_probe import probe_log_formats, union_detected_formats

_MAX_LINE_LEN = 2000


def _collect_log_files(
    root: Path,
    *,
    recursive: bool,
    max_depth: int | None,
) -> list[LogFileInfo]:
    try:
        resolved = root.resolve()
    except OSError:
        resolved = root

    log_files: list[LogFileInfo] = []
    is_file = resolved.is_file()

    for path in discover_log_files(
        resolved,
        recursive=recursive,
        max_depth=max_depth,
    ):
        try:
            if is_file:
                rel = path.name
            else:
                rel = path.relative_to(resolved).as_posix()
            size = path.stat().st_size
        except (OSError, ValueError):
            continue
        log_files.append(
            LogFileInfo(
                relative_path=rel,
                size_bytes=size,
                priority=is_priority_log(path.name),
                log_kind=log_kind_for_path(rel),
            )
        )
    return log_files


def _check_sources(
    logs_path: str,
    caseone_path: str | None,
    *,
    recursive: bool,
    max_depth: int | None,
    path_notes: list[str] | None = None,
) -> SourcesCheck:
    errors: list[str] = list(path_notes or [])
    root = Path(logs_path)
    logs_exists = root.exists()
    logs_is_file = root.is_file() if logs_exists else False
    logs_is_dir = root.is_dir() if logs_exists else False
    log_files: list[LogFileInfo] = []

    if not logs_exists:
        errors.append(f"Путь логов не найден: {logs_path}")
        errors.extend(path_hints_for_missing(logs_path))
    elif not logs_is_dir and not logs_is_file:
        errors.append(f"Путь логов не является каталогом или файлом лога: {logs_path}")
    else:
        log_files = _collect_log_files(root, recursive=recursive, max_depth=max_depth)
        if not log_files:
            hint = (
                "Рекурсивный обход подкалогов включён, но *.log не найдены."
                if recursive
                else "Поиск только в корне каталога; включите recursive=true для подкаталогов."
            )
            errors.append(hint)

    caseone_exists: bool | None = None
    caseone_is_dir: bool | None = None
    if caseone_path and caseone_path.strip():
        co = Path(caseone_path.strip())
        caseone_exists = co.exists()
        caseone_is_dir = co.is_dir() if caseone_exists else False
        if not caseone_exists:
            errors.append(f"Путь caseone не найден: {caseone_path}")
            if is_docker_runtime():
                mount = os.getenv("POC_CASEONE_MOUNT", "/caseone")
                errors.append(
                    f"Смонтируйте caseone в контейнер ({mount}) "
                    "или оставьте поле пустым — для шагов 1–2 он не обязателен."
                )
        elif not caseone_is_dir:
            errors.append(f"Путь caseone не является каталогом: {caseone_path}")

    return SourcesCheck(
        logs_path=logs_path,
        logs_exists=logs_exists,
        logs_is_directory=logs_is_dir,
        logs_is_file=logs_is_file,
        recursive_search=recursive,
        max_depth=max_depth,
        log_file_count=len(log_files),
        log_files=log_files,
        caseone_path=caseone_path.strip() if caseone_path and caseone_path.strip() else None,
        caseone_exists=caseone_exists,
        caseone_is_directory=caseone_is_dir,
        errors=errors,
    )


def _stats_and_samples_from_slice(
    lines: list[TimeWindowLine],
    log_files: list[LogFileInfo],
    *,
    max_per_file: int,
    max_total: int,
) -> tuple[list[FileMatchStats], list[SampleLine]]:
    priority_by_file = {f.relative_path: f.priority for f in log_files}
    counts: dict[str, int] = defaultdict(int)
    for line in lines:
        counts[line.file] += 1

    by_file = [
        FileMatchStats(
            relative_path=rel,
            match_count=count,
            priority=priority_by_file.get(rel, is_priority_log(Path(rel).name)),
        )
        for rel, count in counts.items()
    ]
    by_file.sort(key=lambda x: (-x.priority, -x.match_count, x.relative_path))

    samples: list[SampleLine] = []
    per_file: dict[str, int] = defaultdict(int)
    remaining = max_total
    for line in lines:
        if per_file[line.file] >= max_per_file or remaining <= 0:
            continue
        text = line.text
        if len(text) > _MAX_LINE_LEN:
            text = text[:_MAX_LINE_LEN] + "…"
        samples.append(
            SampleLine(file=line.file, line_number=line.line_number, text=text)
        )
        per_file[line.file] += 1
        remaining -= 1

    return by_file, samples


def _format_summary(detected: dict[str, str]) -> list[str]:
    if not detected:
        return []
    by_fmt: dict[str, int] = {}
    for fmt in detected.values():
        by_fmt[fmt] = by_fmt.get(fmt, 0) + 1
    return [f"{fmt}: {count} файл(ов)" for fmt, count in sorted(by_fmt.items())]


def _expand_patterns(
    req: FilterLogsRequest,
    patterns: list[str],
    formats: tuple[str, ...],
    *,
    start: str | None,
    end: str | None,
) -> tuple[list[str], list[str], bool]:
    if not req.incident_date or not start or not end:
        return patterns, [], False
    before = len(patterns)
    merged, warnings = enrich_log_search_patterns(
        req.incident_date,
        start,
        end,
        patterns,
        formats,
    )
    return merged, warnings, len(merged) > before


def _slice_filter(
    patterns: list[str],
    req: FilterLogsRequest,
    *,
    start: str | None,
    end: str | None,
) -> TimeSliceFilter:
    bounds = datetime_window_bounds(req.incident_date, start, end)
    ws, we = bounds if bounds else (None, None)
    return TimeSliceFilter(
        patterns=tuple(patterns),
        window_start=ws,
        window_end=we,
        strategy=req.time_filter_strategy,
    )


def filter_logs(req: FilterLogsRequest) -> FilterLogsResponse:
    full_corpus = req.time_filter_mode == "full_corpus"
    patterns = [p.strip() for p in req.log_search_patterns if p and p.strip()]
    slow_patterns = [p.strip() for p in req.slow_log_search_patterns if p and p.strip()]
    if not full_corpus and not patterns:
        return FilterLogsResponse(
            status="error",
            step="sources",
            time_filter_mode=req.time_filter_mode,
            errors=["Нужен хотя бы один log_search_pattern или режим full_corpus."],
        )

    path_notes: list[str] = []
    logs_path, note = resolve_host_path(req.logs_path)
    if note:
        path_notes.append(note)
    logs_path = logs_path or req.logs_path

    caseone_path = req.caseone_path
    if caseone_path and caseone_path.strip():
        resolved_co, co_note = resolve_host_path(caseone_path)
        if co_note:
            path_notes.append(co_note)
        caseone_path = resolved_co or caseone_path

    sources = _check_sources(
        logs_path,
        caseone_path,
        recursive=req.recursive,
        max_depth=req.max_depth,
        path_notes=path_notes,
    )

    detected: dict[str, str] = {}
    if sources.log_files and sources.logs_exists:
        detected = probe_log_formats(
            logs_path,
            sources.log_files,
            logs_is_file=sources.logs_is_file,
        )
        sources = sources.model_copy(update={"detected_timestamp_formats": detected})

    formats = union_detected_formats(detected)
    pattern_warnings: list[str] = []
    patterns_expanded = False

    if not full_corpus:
        tw_start = req.time_window_start
        tw_end = req.time_window_end
        patterns, w, exp = _expand_patterns(req, patterns, formats, start=tw_start, end=tw_end)
        pattern_warnings.extend(w)
        patterns_expanded = patterns_expanded or exp

        if slow_patterns != patterns:
            slow_start, slow_end, _ = expand_time_window_hours(
                req.incident_date,
                tw_start,
                tw_end,
                padding_h=DEFAULT_SLOW_PADDING_H,
            )
            slow_patterns, sw, exp2 = _expand_patterns(
                req,
                slow_patterns,
                formats,
                start=slow_start or tw_start,
                end=slow_end or tw_end,
            )
            pattern_warnings.extend(sw)
            patterns_expanded = patterns_expanded or exp2
        elif patterns_expanded:
            slow_patterns = list(patterns)

    main_flt = _slice_filter(
        patterns,
        req,
        start=req.time_window_start,
        end=req.time_window_end,
    )
    slow_start, slow_end = req.time_window_start, req.time_window_end
    if req.incident_date and req.time_window_start and req.time_window_end:
        slow_start, slow_end, _ = expand_time_window_hours(
            req.incident_date,
            req.time_window_start,
            req.time_window_end,
            padding_h=DEFAULT_SLOW_PADDING_H,
        )
    slow_flt = _slice_filter(
        slow_patterns if slow_patterns else patterns,
        req,
        start=slow_start,
        end=slow_end,
    )

    if sources.errors and not sources.log_files:
        return FilterLogsResponse(
            status="error",
            step="sources",
            sources=sources,
            patterns_used=patterns,
            time_filter_mode=req.time_filter_mode,
            errors=sources.errors,
        )

    time_slice, slow_slice = build_dual_time_window_slices(
        sources,
        main_flt,
        slow_flt,
        max_lines=req.max_time_window_lines,
        full_corpus=full_corpus,
    )
    by_file, samples = _stats_and_samples_from_slice(
        time_slice.lines,
        sources.log_files,
        max_per_file=req.max_sample_lines_per_file,
        max_total=req.max_total_sample_lines,
    )

    errors = list(sources.errors) + pattern_warnings
    total = time_slice.total_count
    if full_corpus:
        errors.insert(
            0,
            "Временной интервал не задан: использованы все строки логов (до лимита). "
            "Вывод может быть некорректным — в срез могли попасть события других периодов.",
        )
    elif total == 0 and sources.log_file_count > 0:
        fmt_hint = ", ".join(_format_summary(detected)) or "не определены"
        errors.append(
            f"Строк по паттернам времени не найдено (режим {req.time_filter_strategy}). "
            f"Проверьте дату/окно ({req.incident_date} {req.time_window_start}–{req.time_window_end}). "
            f"Форматы в логах: {fmt_hint}. "
            f"Паттернов: {len(patterns)}."
        )
    if time_slice.truncated:
        errors.append(
            f"Срез обрезан до {len(time_slice.lines)} строк (всего в окне {total}). "
            "Шаги 3–5 используют только сохранённый срез."
        )
    if slow_slice.truncated and slow_slice is not time_slice:
        errors.append(
            f"Расширенный срез (долгие HTTP) обрезан до {len(slow_slice.lines)} строк "
            f"(всего {slow_slice.total_count})."
        )

    critical = not sources.logs_exists or (
        not sources.logs_is_directory and not sources.logs_is_file
    )
    status = "error" if critical else "ok"

    return FilterLogsResponse(
        status=status,
        step="sources_and_filter",
        time_filter_mode=req.time_filter_mode,
        time_filter_strategy=req.time_filter_strategy,
        sources=sources,
        patterns_used=patterns if not full_corpus else [],
        patterns_expanded=patterns_expanded,
        detected_format_summary=_format_summary(detected),
        total_matching_lines=total,
        by_file=by_file,
        sample_lines=samples,
        time_window_lines=time_slice.lines,
        slow_time_window_lines=slow_slice.lines,
        files_in_window=files_in_window(time_slice),
        slow_patterns_used=slow_patterns if not full_corpus else [],
        time_window_truncated=time_slice.truncated,
        slow_time_window_truncated=slow_slice.truncated,
        time_window_total_count=total,
        slow_time_window_total_count=slow_slice.total_count,
        errors=errors,
    )
