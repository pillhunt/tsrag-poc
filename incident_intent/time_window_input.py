"""Входной срез для шагов 3–4: только из шагов 1–2."""

from __future__ import annotations

from incident_intent.log_filter_models import TimeWindowLine
from incident_intent.time_window_slice import TimeWindowSlice, slice_from_request_lines

_MISSING_SLICE_ERROR = (
    "Нужен срез логов из шагов 1–2: выполните «Сузить логи» и передайте time_window_lines, "
    "либо повторите шаг 1–2 перед этим запросом."
)


def require_time_window_slice(
    time_window_lines: list[TimeWindowLine] | None,
) -> tuple[TimeWindowSlice | None, str | None]:
    slice_result = slice_from_request_lines(time_window_lines)
    if slice_result is None or not slice_result.lines:
        return None, _MISSING_SLICE_ERROR
    return slice_result, None
