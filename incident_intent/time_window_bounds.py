"""Границы временного окна как datetime для parse-режима среза."""

from __future__ import annotations

from datetime import datetime

from incident_intent.time_window_utils import _parse_hhmm


def datetime_window_bounds(
    iso_date: str | None,
    start: str | None,
    end: str | None,
) -> tuple[datetime, datetime] | None:
    if not iso_date or not start or not end:
        return None
    sh = _parse_hhmm(start)
    eh = _parse_hhmm(end)
    if not sh or not eh:
        return None
    try:
        d0 = datetime.strptime(iso_date, "%Y-%m-%d").replace(
            hour=sh[0], minute=sh[1], second=0, microsecond=0
        )
        d1 = datetime.strptime(iso_date, "%Y-%m-%d").replace(
            hour=eh[0], minute=eh[1], second=59, microsecond=999999
        )
    except ValueError:
        return None
    if d1 < d0:
        d1 = d0.replace(second=59, microsecond=999999)
    return d0, d1
