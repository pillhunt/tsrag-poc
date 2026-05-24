"""Проверка фраз «достаточно / продолжай» от пользователя."""

from __future__ import annotations

import re

_ENOUGH_PATTERNS = (
    r"^\s*(пропустить|skip|нет)\s*$",
    r"достаточно",
    r"продолжай",
    r"продолжить",
    r"больше\s+нечего",
    r"уточнений\s+больше\s+нет",
    r"больше\s+не\s+уточн",
    r"это\s+вс[её]",
    r"^ok\s*$",
    r"^ок\s*$",
)


def is_user_done_message(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return False
    for pat in _ENOUGH_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False
