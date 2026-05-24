"""Разбор строк RequestLoggingMiddleware: метод, API, длительность (мс)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_RE_TIMESTAMP = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)
_RE_REQUEST = re.compile(
    r";\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*;\s*(/api/[^\s;]+)\s*;\s*[^;]*;\s*(\d+)\s*;",
    re.IGNORECASE,
)
_RE_REQUEST_ALT = re.compile(
    r"\|\s*(GET|POST|PUT|DELETE|PATCH)\s*;\s*(/api/[^\s;]+)\s*;\s*[^;]*;\s*(\d+)\s*;",
    re.IGNORECASE,
)

MIDDLEWARE_NAME_PART = "RequestLoggingMiddleware"


@dataclass(frozen=True)
class ParsedSlowRequest:
    ended_at: str | None
    method: str
    path: str
    duration_ms: int
    source_file: str
    line_number: int


def is_middleware_log(relative_path: str) -> bool:
    return MIDDLEWARE_NAME_PART.lower() in relative_path.replace("\\", "/").lower()


def parse_request_line(
    line: str,
    *,
    source_file: str,
    line_number: int,
) -> ParsedSlowRequest | None:
    match = _RE_REQUEST.search(line) or _RE_REQUEST_ALT.search(line)
    if not match:
        return None
    try:
        duration_ms = int(match.group(3))
    except ValueError:
        return None
    if duration_ms < 0:
        return None

    ts_match = _RE_TIMESTAMP.search(line)
    ended_at = ts_match.group(1) if ts_match else None

    return ParsedSlowRequest(
        ended_at=ended_at,
        method=match.group(1).upper(),
        path=match.group(2).strip(),
        duration_ms=duration_ms,
        source_file=source_file,
        line_number=line_number,
    )


def duration_to_minutes(duration_ms: int) -> float:
    return round(duration_ms / 60_000, 1)
