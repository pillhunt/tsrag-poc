"""Применение мульти-форматных паттернов к таблице намерений."""

from __future__ import annotations

from incident_intent.models import IntentTable
from incident_intent.time_pattern_factory import DEFAULT_FORMATS, enrich_log_search_patterns
from incident_intent.time_window_utils import (
    DEFAULT_SLOW_PADDING_H,
    expand_time_window_hours,
)


def apply_multi_format_patterns(table: IntentTable) -> None:
    date = table.incident_date.value
    start = table.time_window_start.value
    end = table.time_window_end.value
    if not date or not start or not end or table.time_filter_mode == "full_corpus":
        return

    merged, warnings = enrich_log_search_patterns(
        date,
        start,
        end,
        table.log_search_patterns,
        DEFAULT_FORMATS,
    )
    table.log_search_patterns = merged
    table.notes.extend(warnings)

    slow_start, slow_end, _ = expand_time_window_hours(
        date,
        start,
        end,
        padding_h=DEFAULT_SLOW_PADDING_H,
    )
    slow_existing = table.slow_log_search_patterns or list(merged)
    merged_slow, slow_warnings = enrich_log_search_patterns(
        date,
        slow_start or start,
        slow_end or end,
        slow_existing,
        DEFAULT_FORMATS,
    )
    table.slow_log_search_patterns = merged_slow
    table.notes.extend(slow_warnings)
