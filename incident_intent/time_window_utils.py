"""Окно времени: ±padding для одной метки, почасовые grep-паттерны."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

DEFAULT_PADDING_MIN = int(os.getenv("POC_TIME_PADDING_MIN", "10"))
DEFAULT_SLOW_PADDING_H = int(os.getenv("POC_SLOW_WINDOW_PADDING_H", "1"))


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    parts = value.strip().split(":")
    if not parts:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h, m


def expand_single_time_window(
    iso_date: str | None,
    start: str | None,
    end: str | None,
    *,
    padding_min: int = DEFAULT_PADDING_MIN,
) -> tuple[str | None, str | None, list[str]]:
    """
    Если задана одна метка времени (или start == end) — расширить на ±padding_min.
    Возвращает (start, end, notes).
    """
    notes: list[str] = []
    if not iso_date:
        return start, end, notes

    s = start.strip() if start else None
    e = end.strip() if end else None
    if s in ("", "null"):
        s = None
    if e in ("", "null"):
        e = None

    if s and not e:
        e = s
    elif e and not s:
        s = e

    if not s or not e:
        return start, end, notes

    if s != e:
        return s, e, notes

    sh, sm = _parse_hhmm(s) or (0, 0)
    try:
        anchor = datetime.strptime(iso_date, "%Y-%m-%d").replace(hour=sh, minute=sm)
    except ValueError:
        return s, e, notes

    lo = anchor - timedelta(minutes=padding_min)
    hi = anchor + timedelta(minutes=padding_min)
    new_start = lo.strftime("%H:%M")
    new_end = hi.strftime("%H:%M")
    notes.append(
        f"Указано одно время ({s}); для поиска использовано окно ±{padding_min} мин "
        f"({new_start}–{new_end})."
    )
    return new_start, new_end, notes


def hour_patterns(iso_date: str | None, start: str | None, end: str | None) -> list[str]:
    if not iso_date or not start or not end:
        return []
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
    return [f"{iso_date} {h:02d}:" for h in sorted(hours)]


def expand_time_window_hours(
    iso_date: str | None,
    start: str | None,
    end: str | None,
    *,
    padding_h: int = DEFAULT_SLOW_PADDING_H,
) -> tuple[str | None, str | None, list[str]]:
    """
    Расширить окно жалобы на ±padding_h часов — для долгих HTTP (могли начаться раньше).
    """
    notes: list[str] = []
    if not iso_date or not start or not end or padding_h <= 0:
        return start, end, notes

    sh = _parse_hhmm(start)
    eh = _parse_hhmm(end)
    if not sh or not eh:
        return start, end, notes

    try:
        d0 = datetime.strptime(iso_date, "%Y-%m-%d").replace(hour=sh[0], minute=sh[1])
        d1 = datetime.strptime(iso_date, "%Y-%m-%d").replace(hour=eh[0], minute=eh[1])
    except ValueError:
        return start, end, notes

    if d1 < d0:
        d1 = d0

    lo = d0 - timedelta(hours=padding_h)
    hi = d1 + timedelta(hours=padding_h)
    new_start = lo.strftime("%H:%M")
    new_end = hi.strftime("%H:%M")
    notes.append(
        f"Окно для долгих HTTP расширено на ±{padding_h} ч от жалобы "
        f"({start}–{end} → {new_start}–{new_end})."
    )
    return new_start, new_end, notes


def slow_log_search_patterns(
    iso_date: str | None,
    start: str | None,
    end: str | None,
    *,
    padding_h: int = DEFAULT_SLOW_PADDING_H,
) -> tuple[list[str], list[str]]:
    """Паттерны grep для расширенного окна долгих запросов + notes."""
    if not iso_date or not start or not end:
        return [], []
    slow_start, slow_end, notes = expand_time_window_hours(
        iso_date, start, end, padding_h=padding_h
    )
    patterns = hour_patterns(iso_date, slow_start, slow_end)
    return patterns, notes
