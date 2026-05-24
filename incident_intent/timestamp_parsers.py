"""Извлечение метки времени из строк логов разных форматов."""

from __future__ import annotations

import re
from datetime import datetime

_RE_ISO = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)
_RE_NGINX = re.compile(
    r"\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}(?:\s[+-]\d{4})?)\]"
)
_RE_IIS_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_RE_IIS_TIME = re.compile(r"\b(\d{2}:\d{2}:\d{2})\b")


def parse_log_timestamp(text: str, *, file_path: str = "") -> datetime | None:
    """Пробует несколько форматов; file_path — подсказка для IIS W3C."""
    match = _RE_ISO.search(text)
    if match:
        return _parse_iso(match.group(1))

    match = _RE_NGINX.search(text)
    if match:
        raw = match.group(1).split()[0]
        try:
            return datetime.strptime(raw, "%d/%b/%Y:%H:%M:%S")
        except ValueError:
            pass

    lower = file_path.replace("\\", "/").lower()
    if "u_ex" in lower or "w3svc" in lower:
        date_m = _RE_IIS_DATE.search(text)
        time_m = _RE_IIS_TIME.search(text)
        if date_m and time_m:
            try:
                return datetime.strptime(
                    f"{date_m.group(1)} {time_m.group(1)}",
                    "%Y-%m-%d %H:%M:%S",
                )
            except ValueError:
                pass

    return None


def _parse_iso(raw: str) -> datetime | None:
    try:
        if "." in raw:
            date_part, frac = raw.split(".", 1)
            frac = (frac + "000000")[:6]
            return datetime.strptime(f"{date_part}.{frac}", "%Y-%m-%d %H:%M:%S.%f")
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
