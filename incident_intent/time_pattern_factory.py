"""Генерация grep-паттернов времени для разных форматов логов."""

from __future__ import annotations

from datetime import datetime, timedelta

from incident_intent.time_window_utils import _parse_hhmm

DEFAULT_FORMATS: tuple[str, ...] = ("iso_space", "iso_t", "nginx", "eu_dot")
_MAX_PATTERNS = 128

_MONTHS_EN = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _hours_in_window(iso_date: str, start: str, end: str) -> list[tuple[datetime, int]]:
    sh = _parse_hhmm(start)
    eh = _parse_hhmm(end)
    if not sh or not eh:
        return []
    try:
        d0 = datetime.strptime(iso_date, "%Y-%m-%d").replace(hour=sh[0], minute=sh[1])
        d1 = datetime.strptime(iso_date, "%Y-%m-%d").replace(hour=eh[0], minute=eh[1])
    except ValueError:
        return []
    if d1 < d0:
        d1 = d0
    hours: set[int] = set()
    cur = d0.replace(minute=0, second=0, microsecond=0)
    end_hour = d1.replace(minute=0, second=0, microsecond=0)
    while cur <= end_hour:
        hours.add(cur.hour)
        cur += timedelta(hours=1)
    hours.add(d0.hour)
    hours.add(d1.hour)
    try:
        base = datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        return []
    return [(base.replace(hour=h), h) for h in sorted(hours)]


def pattern_for_hour(iso_date: str, hour: int, fmt: str) -> str | None:
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d").replace(hour=hour)
    except ValueError:
        return None
    hh = f"{hour:02d}"
    if fmt == "iso_space":
        return f"{iso_date} {hh}:"
    if fmt == "iso_t":
        return f"{iso_date}T{hh}:"
    if fmt == "nginx":
        return f"[{dt.day:02d}/{_MONTHS_EN[dt.month - 1]}/{dt.year}:{hh}:"
    if fmt == "eu_dot":
        return f"{dt.day:02d}.{dt.month:02d}.{dt.year} {hh}:"
    if fmt == "eu_dot_short":
        return f"{dt.day:02d}.{dt.month:02d}.{dt.year % 100:02d} {hh}:"
    return None


def patterns_for_window(
    iso_date: str | None,
    start: str | None,
    end: str | None,
    formats: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    if not iso_date or not start or not end:
        return []
    fmts = tuple(formats) if formats else DEFAULT_FORMATS
    out: list[str] = []
    seen: set[str] = set()
    for _base, hour in _hours_in_window(iso_date, start, end):
        for fmt in fmts:
            pat = pattern_for_hour(iso_date, hour, fmt)
            if pat and pat not in seen:
                seen.add(pat)
                out.append(pat)
    return out


def merge_patterns(
    existing: list[str],
    generated: list[str],
    *,
    max_patterns: int = _MAX_PATTERNS,
) -> tuple[list[str], list[str]]:
    """Объединить паттерны LLM и factory; вернуть (merged, warnings)."""
    warnings: list[str] = []
    seen: set[str] = set()
    merged: list[str] = []
    for p in existing + generated:
        p = p.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        merged.append(p)
    if len(merged) > max_patterns:
        warnings.append(
            f"Паттернов времени {len(merged)} — больше лимита {max_patterns}; "
            f"используются первые {max_patterns}."
        )
        merged = merged[:max_patterns]
    return merged, warnings


def enrich_log_search_patterns(
    iso_date: str | None,
    start: str | None,
    end: str | None,
    existing: list[str],
    formats: tuple[str, ...] | list[str] | None = None,
) -> tuple[list[str], list[str]]:
    generated = patterns_for_window(iso_date, start, end, formats)
    return merge_patterns(existing, generated)
