"""Извлечение метки времени из строк логов разных форматов."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

_RE_ISO = re.compile(
    r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)
_RE_NGINX = re.compile(
    r"\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}(?:\s[+-]\d{4})?)\]"
)
_RE_EU_DOT = re.compile(
    r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)
_RE_EU_DOT_SHORT = re.compile(
    r"(\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})"
)
_RE_IIS_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_RE_IIS_TIME = re.compile(r"\b(\d{2}:\d{2}:\d{2})\b")

DetectFn = Callable[[str, str], str | None]


def _parse_iso(raw: str) -> datetime | None:
    normalized = raw.replace("T", " ", 1)
    try:
        if "." in normalized:
            date_part, frac = normalized.split(".", 1)
            frac = (frac + "000000")[:6]
            return datetime.strptime(f"{date_part}.{frac}", "%Y-%m-%d %H:%M:%S.%f")
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _detect_iso(line: str, _file: str) -> str | None:
    return "iso_space" if _RE_ISO.search(line) else None


def _detect_nginx(line: str, _file: str) -> str | None:
    return "nginx" if _RE_NGINX.search(line) else None


def _detect_eu_dot(line: str, _file: str) -> str | None:
    if _RE_EU_DOT.search(line):
        return "eu_dot"
    if _RE_EU_DOT_SHORT.search(line):
        return "eu_dot_short"
    return None


def _detect_iis(line: str, file_path: str) -> str | None:
    lower = file_path.replace("\\", "/").lower()
    if "u_ex" not in lower and "w3svc" not in lower:
        return None
    if line.startswith("#"):
        return "iis_w3c" if "date" in line.lower() and "time" in line.lower() else None
    if _RE_IIS_DATE.search(line) and _RE_IIS_TIME.search(line):
        return "iis_w3c"
    return None


_DETECTORS: tuple[tuple[str, DetectFn], ...] = (
    ("nginx", _detect_nginx),
    ("iso_space", _detect_iso),
    ("eu_dot", _detect_eu_dot),
    ("iis_w3c", _detect_iis),
)


def detect_timestamp_format(text: str, *, file_path: str = "") -> str | None:
    for _name, fn in _DETECTORS:
        hit = fn(text, file_path)
        if hit:
            return hit
    return None


def parse_log_timestamp(text: str, *, file_path: str = "") -> datetime | None:
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

    match = _RE_EU_DOT.search(text)
    if match:
        try:
            return datetime.strptime(match.group(1), "%d.%m.%Y %H:%M:%S.%f")
        except ValueError:
            try:
                return datetime.strptime(match.group(1), "%d.%m.%Y %H:%M:%S")
            except ValueError:
                pass

    match = _RE_EU_DOT_SHORT.search(text)
    if match:
        try:
            return datetime.strptime(match.group(1), "%d.%m.%y %H:%M:%S")
        except ValueError:
            pass

    lower = file_path.replace("\\", "/").lower()
    if "u_ex" in lower or "w3svc" in lower:
        if not text.startswith("#"):
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
