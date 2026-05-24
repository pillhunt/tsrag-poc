"""
Шаг 3: поиск по search_keywords только в срезе строк из шагов 1–2.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from incident_intent.keyword_utils import find_matching_keyword, merge_keywords
from incident_intent.log_discovery import is_priority_log
from incident_intent.symptom_search_models import (
    SymptomFileStats,
    SymptomSampleLine,
    SymptomSearchRequest,
    SymptomSearchResponse,
)
from incident_intent.time_window_input import require_time_window_slice

_MAX_LINE_LEN = 2000


def _truncate(line: str) -> str:
    if len(line) <= _MAX_LINE_LEN:
        return line
    return line[:_MAX_LINE_LEN] + "…"


def _build_conclusions(total: int, keywords: list[str], *, from_slice: int) -> list[str]:
    if total == 0:
        return [
            f"В срезе шагов 1–2 ({from_slice} строк) нет совпадений по search_keywords.",
            "Проверьте ключевые слова на шаге 0 или расширьте временное окно.",
            "Следующий шаг — долгие HTTP-запросы (шаг 4) по тому же срезу.",
        ]
    return [
        f"Найдено {total} строк (из {from_slice} в срезе) по {len(keywords)} ключевым словам.",
        "Следующий шаг — долгие запросы в RequestLoggingMiddleware (шаг 4).",
    ]


def search_symptoms(req: SymptomSearchRequest) -> SymptomSearchResponse:
    keywords = merge_keywords(req.search_keywords, req.extra_keywords)
    if not keywords:
        return SymptomSearchResponse(
            status="error",
            errors=["Нужен хотя бы один search_keyword (шаг 0) или extra_keywords."],
        )

    time_slice, slice_err = require_time_window_slice(req.time_window_lines)
    if slice_err or time_slice is None:
        return SymptomSearchResponse(status="error", errors=[slice_err or "Нет среза"])

    file_counts: dict[str, int] = defaultdict(int)
    samples: list[SymptomSampleLine] = []
    per_file_sample: dict[str, int] = defaultdict(int)
    remaining = req.max_total_sample_lines
    total = 0

    for line in time_slice.lines:
        matched = find_matching_keyword(line.text, keywords)
        if not matched:
            continue

        total += 1
        file_counts[line.file] += 1

        cap = req.max_sample_lines_per_file
        if per_file_sample[line.file] < cap and remaining > 0:
            samples.append(
                SymptomSampleLine(
                    file=line.file,
                    line_number=line.line_number,
                    text=_truncate(line.text),
                    matched_keyword=matched,
                )
            )
            per_file_sample[line.file] += 1
            remaining -= 1

    by_file = [
        SymptomFileStats(
            relative_path=rel,
            match_count=count,
            priority=is_priority_log(Path(rel).name),
        )
        for rel, count in sorted(file_counts.items(), key=lambda x: (-x[1], x[0]))
    ]
    by_file.sort(key=lambda x: (-x.priority, -x.match_count, x.relative_path))

    return SymptomSearchResponse(
        status="ok",
        time_patterns_used=req.log_search_patterns,
        search_keywords_used=keywords,
        total_matching_lines=total,
        by_file=by_file,
        sample_lines=samples,
        conclusions=_build_conclusions(
            total,
            keywords,
            from_slice=len(time_slice.lines),
        ),
        errors=[],
    )
