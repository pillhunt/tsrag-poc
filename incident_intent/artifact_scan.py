"""
Скан артефактов: keywords и якоря в узком и широком временном окне (построчно с диска).
"""

from __future__ import annotations

import re
from collections import defaultdict

from incident_intent.artifact_scan_models import (
    ArtifactSampleLine,
    ArtifactScanRequest,
    ArtifactScanResponse,
    WindowHitCounts,
)
from incident_intent.error_classifier import classify_error_line, matched_pattern
from incident_intent.keyword_utils import find_matching_keyword, merge_keywords, normalize_search_keywords
from incident_intent.log_filter import filter_logs
from incident_intent.log_filter_models import FilterLogsRequest
from incident_intent.log_scan import TimeSliceFilter, line_in_time_window
from incident_intent.path_resolve import resolve_host_path
from incident_intent.time_window_bounds import datetime_window_bounds
from incident_intent.time_window_utils import DEFAULT_SLOW_PADDING_H, expand_time_window_hours

_RE_API_PATH = re.compile(r"/api/[^\s\"'<>]{3,120}")

_MAX_LINE = 500
_DEFAULT_SAMPLES_PER_MATCH = int(__import__("os").getenv("POC_ARTIFACT_SCAN_MAX_SAMPLES_PER_MATCH", "3"))
_MAX_DISCOVERED = int(__import__("os").getenv("POC_ARTIFACT_SCAN_MAX_DISCOVERED_ANCHORS", "30"))


def _slice_filter(
    patterns: list[str],
    req: ArtifactScanRequest,
    *,
    start: str | None,
    end: str | None,
    strategy: str,
) -> TimeSliceFilter:
    bounds = datetime_window_bounds(req.incident_date, start, end)
    ws, we = bounds if bounds else (None, None)
    return TimeSliceFilter(
        patterns=tuple(patterns),
        window_start=ws,
        window_end=we,
        strategy=strategy,
    )


def _line_in_window(
    text: str,
    file_path: str,
    *,
    narrow_flt: TimeSliceFilter,
    wide_flt: TimeSliceFilter,
    full_corpus: bool,
) -> tuple[bool, bool]:
    if full_corpus:
        return True, True
    in_narrow = line_in_time_window(text, file_path=file_path, flt=narrow_flt)
    in_wide = line_in_time_window(text, file_path=file_path, flt=wide_flt)
    return in_narrow, in_wide


def _extract_api_paths(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in _RE_API_PATH.finditer(text)))


def _discover_from_error(text: str, file_path: str) -> list[str]:
    classified = classify_error_line(text, file_path=file_path)
    if classified is None:
        return []
    _engine, category = classified
    out: list[str] = [category]
    marker = matched_pattern(text, category, file_path=file_path)
    if marker and marker != category:
        out.append(marker)
    return out


def _bump(counts: dict[str, WindowHitCounts], key: str, *, narrow: bool, wide: bool) -> None:
    if key not in counts:
        counts[key] = WindowHitCounts()
    if narrow:
        counts[key].narrow += 1
    if wide:
        counts[key].wide += 1


def _try_sample(
    samples: list[ArtifactSampleLine],
    per_key: dict[str, int],
    *,
    limit: int,
    file: str,
    line_no: int,
    window: str,
    matched: str,
    text: str,
) -> None:
    if per_key[matched] >= limit:
        return
    trimmed = text if len(text) <= _MAX_LINE else text[:_MAX_LINE] + "…"
    samples.append(
        ArtifactSampleLine(
            file=file,
            line_number=line_no,
            window=window,  # type: ignore[arg-type]
            matched=matched,
            text=trimmed,
        )
    )
    per_key[matched] += 1


def scan_artifacts(req: ArtifactScanRequest) -> ArtifactScanResponse:
    keywords = normalize_search_keywords(req.search_keywords)
    intent_anchors = normalize_search_keywords(req.anchors)

    logs_path, note = resolve_host_path(req.logs_path)
    logs_path = logs_path or req.logs_path
    path_notes = [note] if note else []

    filt = filter_logs(
        FilterLogsRequest(
            logs_path=logs_path,
            caseone_path=req.caseone_path,
            log_search_patterns=list(req.log_search_patterns or []),
            slow_log_search_patterns=list(
                req.slow_log_search_patterns or req.log_search_patterns or []
            ),
            incident_date=req.incident_date,
            time_window_start=req.time_window_start,
            time_window_end=req.time_window_end,
            time_filter_strategy=req.time_filter_strategy,
            time_filter_mode=req.time_filter_mode,
            recursive=req.recursive,
            max_depth=req.max_depth,
            max_sample_lines_per_file=0,
            max_total_sample_lines=0,
        )
    )
    if path_notes:
        filt.errors = list(path_notes) + list(filt.errors)

    sources = filt.sources
    if not sources or not sources.log_files:
        return ArtifactScanResponse(
            status="error",
            errors=filt.errors or ["Нет файлов логов для скана артефактов."],
        )

    full_corpus = req.time_filter_mode == "full_corpus"
    patterns = list(filt.patterns_used or req.log_search_patterns or [])
    slow_patterns = list(filt.slow_patterns_used or patterns)

    tw_start, tw_end = req.time_window_start, req.time_window_end
    slow_start, slow_end = tw_start, tw_end
    if req.incident_date and tw_start and tw_end:
        slow_start, slow_end, _ = expand_time_window_hours(
            req.incident_date,
            tw_start,
            tw_end,
            padding_h=DEFAULT_SLOW_PADDING_H,
        )

    narrow_flt = _slice_filter(
        patterns,
        req,
        start=tw_start,
        end=tw_end,
        strategy=req.time_filter_strategy,
    )
    wide_flt = _slice_filter(
        slow_patterns,
        req,
        start=slow_start or tw_start,
        end=slow_end or tw_end,
        strategy=req.time_filter_strategy,
    )

    keyword_hits: dict[str, WindowHitCounts] = {}
    anchor_hits: dict[str, WindowHitCounts] = {}
    discovered_set: set[str] = set()
    discovered_order: list[str] = []

    def _add_discovered(token: str) -> None:
        norm = normalize_search_keywords([token])
        if not norm:
            return
        t = norm[0]
        key = t.casefold()
        if key in discovered_set:
            return
        if len(discovered_order) >= _MAX_DISCOVERED:
            return
        discovered_set.add(key)
        discovered_order.append(t)

    samples: list[ArtifactSampleLine] = []
    kw_samples: dict[str, int] = defaultdict(int)
    anch_samples: dict[str, int] = defaultdict(int)

    narrow_lines = 0
    wide_lines = 0

    from incident_intent.log_scan import iter_all_log_lines

    for rel, line_no, text in iter_all_log_lines(sources):
        in_narrow, in_wide = _line_in_window(
            text,
            rel,
            narrow_flt=narrow_flt,
            wide_flt=wide_flt,
            full_corpus=full_corpus,
        )
        if not in_narrow and not in_wide:
            continue

        if in_narrow:
            narrow_lines += 1
        if in_wide:
            wide_lines += 1

        for token in _extract_api_paths(text):
            _add_discovered(token)
        for token in _discover_from_error(text, rel):
            _add_discovered(token)

        kw = find_matching_keyword(text, keywords)
        if kw:
            _bump(keyword_hits, kw, narrow=in_narrow, wide=in_wide)
            if in_narrow:
                _try_sample(
                    samples,
                    kw_samples,
                    limit=_DEFAULT_SAMPLES_PER_MATCH,
                    file=rel,
                    line_no=line_no,
                    window="narrow",
                    matched=kw,
                    text=text,
                )
            elif in_wide:
                _try_sample(
                    samples,
                    kw_samples,
                    limit=_DEFAULT_SAMPLES_PER_MATCH,
                    file=rel,
                    line_no=line_no,
                    window="wide",
                    matched=kw,
                    text=text,
                )

        all_anchors = merge_keywords(intent_anchors, discovered_order)
        anchor = find_matching_keyword(text, all_anchors)
        if anchor:
            _bump(anchor_hits, anchor, narrow=in_narrow, wide=in_wide)
            bucket = anch_samples
            if in_narrow:
                _try_sample(
                    samples,
                    bucket,
                    limit=_DEFAULT_SAMPLES_PER_MATCH,
                    file=rel,
                    line_no=line_no,
                    window="narrow",
                    matched=anchor,
                    text=text,
                )
            elif in_wide:
                _try_sample(
                    samples,
                    bucket,
                    limit=_DEFAULT_SAMPLES_PER_MATCH,
                    file=rel,
                    line_no=line_no,
                    window="wide",
                    matched=anchor,
                    text=text,
                )

    anchors_for_search = merge_keywords(intent_anchors, discovered_order)

    conclusions: list[str] = [
        f"Строк в узком окне: {narrow_lines}, в широком: {wide_lines}.",
        f"Keywords: {len(keyword_hits)}, якорей (intent+логи): {len(anchors_for_search)}.",
    ]
    if discovered_order:
        conclusions.append(
            f"Из логов извлечено якорей: {len(discovered_order)}."
        )

    return ArtifactScanResponse(
        status="ok",
        narrow_line_count=narrow_lines,
        wide_line_count=wide_lines,
        keyword_hits=keyword_hits,
        anchor_hits=anchor_hits,
        discovered_anchors=discovered_order,
        anchors_for_search=anchors_for_search,
        samples=samples,
        conclusions=conclusions,
        errors=list(filt.errors)[:5],
    )
