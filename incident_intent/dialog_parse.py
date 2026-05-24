"""Извлечение даты и времени из текста диалога (без LLM)."""

from __future__ import annotations

import re

_RE_DATE_DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_RE_DATE_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_RE_TIME_RANGE = re.compile(
    r"(?:с\s+)?(\d{1,2})(?::(\d{2}))?\s*до\s*(\d{1,2})[:.](\d{2})",
    re.IGNORECASE,
)
_RE_SINGLE_TIME = re.compile(
    r"(?:около|~|≈)\s*(\d{1,2})(?::(\d{2}))?\s*вечер",
    re.IGNORECASE,
)


def user_lines_from_dialog(dialog_text: str) -> list[str]:
    lines: list[str] = []
    for raw in dialog_text.splitlines():
        line = raw.strip()
        if line.startswith("Пользователь:"):
            part = line.split(":", 1)[1].strip()
            if part:
                lines.append(part)
    if not lines and dialog_text.strip():
        lines.append(dialog_text.strip())
    return lines


def parse_date_from_text(text: str) -> str | None:
    m = _RE_DATE_ISO.search(text)
    if m:
        return m.group(1)
    m = _RE_DATE_DMY.search(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def _apply_evening(hour: int, text: str) -> int:
    if re.search(r"вечер", text, re.IGNORECASE) and hour < 12:
        return hour + 12
    return hour


def parse_time_window_from_text(text: str) -> tuple[str | None, str | None]:
    m = _RE_TIME_RANGE.search(text)
    if m:
        sh = _apply_evening(int(m.group(1)), text)
        sm = int(m.group(2) or 0)
        eh = _apply_evening(int(m.group(3)), text)
        em = int(m.group(4))
        return f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}"

    m = _RE_SINGLE_TIME.search(text)
    if m:
        sh = _apply_evening(int(m.group(1)), text)
        sm = int(m.group(2) or 0)
        t = f"{sh:02d}:{sm:02d}"
        return t, t

    return None, None


def parse_date_from_dialog(dialog_text: str) -> str | None:
    for line in reversed(user_lines_from_dialog(dialog_text)):
        found = parse_date_from_text(line)
        if found:
            return found
    return parse_date_from_text(dialog_text)


def parse_time_from_dialog(dialog_text: str) -> tuple[str | None, str | None]:
    for line in reversed(user_lines_from_dialog(dialog_text)):
        start, end = parse_time_window_from_text(line)
        if start and end:
            return start, end
    return parse_time_window_from_text(dialog_text)


def is_datetime_clarification(question: str) -> bool:
    q = question.lower()
    return any(
        w in q
        for w in (
            "дата",
            "время",
            "когда",
            "интервал",
            "какое время",
            "какая дата",
        )
    )
