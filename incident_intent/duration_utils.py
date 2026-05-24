"""Порог «долгого» HTTP из жалобы и ответа LLM (шаг 0 → шаг 4)."""

from __future__ import annotations

import os
import re

DEFAULT_MIN_SLOW_MS = int(os.getenv("POC_DEFAULT_MIN_SLOW_MS", "60000"))
_MAX_MIN_SLOW_MS = 3_600_000
_MIN_MIN_SLOW_MS = 1_000

_RE_MINUTES = re.compile(
    r"(?:~|около\s+|примерно\s+)?(\d+(?:[.,]\d+)?)\s*(?:–|-|\.\.\.)?\s*(\d+(?:[.,]\d+)?)?\s*(?:мин(?:ут)?|min(?:ute)?s?\b)",
    re.IGNORECASE,
)
_RE_SECONDS = re.compile(
    r"(?:~|около\s+|примерно\s+)?(\d+(?:[.,]\d+)?)\s*(?:–|-|\.\.\.)?\s*(\d+(?:[.,]\d+)?)?\s*сек",
    re.IGNORECASE,
)


def _to_float(token: str | None) -> float | None:
    if not token:
        return None
    try:
        return float(token.replace(",", "."))
    except ValueError:
        return None


def _clamp_ms(value: int) -> int:
    return max(_MIN_MIN_SLOW_MS, min(value, _MAX_MIN_SLOW_MS))


def _infer_from_text(text: str) -> int | None:
    if not text:
        return None
    lower = text.casefold()
    m_min = _RE_MINUTES.search(lower)
    if m_min:
        lo = _to_float(m_min.group(1))
        hi = _to_float(m_min.group(2))
        if lo is not None:
            # «20–30 мин» → порог ~⅓ нижней границы; «~5 мин» → ~5 мин
            base = lo if hi is None else min(lo, hi * 0.25)
            return _clamp_ms(int(base * 60_000))
    m_sec = _RE_SECONDS.search(lower)
    if m_sec:
        lo = _to_float(m_sec.group(1))
        if lo is not None:
            return _clamp_ms(int(lo * 1000))
    if "полчас" in lower or "30 мин" in lower:
        return _clamp_ms(10 * 60_000)
    return None


def normalize_min_slow_request_ms(
    raw_ms: int | float | str | None,
    *,
    reported_min_minutes: float | None = None,
    reported_max_minutes: float | None = None,
    context_text: str = "",
) -> tuple[int, list[str]]:
    """Вернуть (milliseconds, notes)."""
    notes: list[str] = []

    if raw_ms is not None:
        try:
            ms = int(float(raw_ms))
            if ms > 0:
                notes.append(f"Порог долгих запросов: {ms} мс (из таблицы намерений).")
                return _clamp_ms(ms), notes
        except (TypeError, ValueError):
            pass

    if reported_min_minutes is not None and reported_min_minutes > 0:
        ms = _clamp_ms(int(reported_min_minutes * 60_000))
        notes.append(
            f"Порог долгих запросов: {ms} мс (из reported_duration_min_minutes={reported_min_minutes})."
        )
        return ms, notes

    if reported_max_minutes is not None and reported_max_minutes > 0:
        ms = _clamp_ms(int(reported_max_minutes * 0.25 * 60_000))
        notes.append(
            f"Порог долгих запросов: {ms} мс (¼ от reported_duration_max_minutes={reported_max_minutes})."
        )
        return ms, notes

    inferred = _infer_from_text(context_text)
    if inferred is not None:
        notes.append(f"Порог долгих запросов: {inferred} мс (из текста жалобы).")
        return inferred, notes

    notes.append(f"Порог долгих запросов: {DEFAULT_MIN_SLOW_MS} мс (значение по умолчанию).")
    return DEFAULT_MIN_SLOW_MS, notes
