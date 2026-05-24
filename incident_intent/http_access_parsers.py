"""Chain-парсеры долгих HTTP/access-запросов из строк лога."""

from __future__ import annotations

import json
import re

from incident_intent.slow_request_parser import parse_request_line as parse_caseone_line
from incident_intent.timestamp_parsers import parse_log_timestamp

_RE_NGINX_RT = re.compile(
    r'"(\w+)\s+([^\s"]+)\s+HTTP/[^"]+"\s+\d+\s+\d+(?:\s+"[^"]*"){0,2}\s+rt=([\d.]+)',
    re.IGNORECASE,
)
_RE_NGINX_UPSTREAM = re.compile(
    r'upstream_response_time=([\d.]+).*?"(\w+)\s+([^\s"]+)',
    re.IGNORECASE,
)
_RE_GENERIC_HTTP = re.compile(
    r"\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+([^\s;\"]+).*?\b(\d{4,})\b",
    re.IGNORECASE,
)
_RE_GENERIC_HTTP_SEC = re.compile(
    r"\b(GET|POST|PUT|DELETE|PATCH)\s+([^\s;\"]+).*?\b(\d+(?:\.\d+)?)\s*s\b",
    re.IGNORECASE,
)


class ParsedHttpAccess:
    __slots__ = ("ended_at", "method", "path", "duration_ms", "log_format")

    def __init__(
        self,
        *,
        ended_at: str | None,
        method: str,
        path: str,
        duration_ms: int,
        log_format: str,
    ) -> None:
        self.ended_at = ended_at
        self.method = method
        self.path = path
        self.duration_ms = duration_ms
        self.log_format = log_format


def parse_http_access_line(
    line: str,
    *,
    source_file: str,
    line_number: int,
) -> ParsedHttpAccess | None:
    del line_number

    caseone = parse_caseone_line(line, source_file=source_file, line_number=0)
    if caseone:
        return ParsedHttpAccess(
            ended_at=caseone.ended_at,
            method=caseone.method,
            path=caseone.path,
            duration_ms=caseone.duration_ms,
            log_format="caseone_middleware",
        )

    for parser in (
        _parse_nginx_combined,
        _parse_nginx_json,
        lambda ln: _parse_iis_w3c(ln, source_file),
        lambda ln: _parse_generic(ln, source_file),
    ):
        parsed = parser(line)
        if parsed:
            return parsed
    return None


def _ts_str(line: str, source_file: str) -> str | None:
    ts = parse_log_timestamp(line, file_path=source_file)
    if ts is None:
        return None
    return ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]


def _parse_nginx_combined(line: str) -> ParsedHttpAccess | None:
    match = _RE_NGINX_RT.search(line) or _RE_NGINX_UPSTREAM.search(line)
    if not match:
        return None
    if match.re is _RE_NGINX_RT:
        method, path, rt = match.group(1), match.group(2), match.group(3)
    else:
        rt, method, path = match.group(1), match.group(2), match.group(3)
    try:
        duration_ms = int(float(rt) * 1000)
    except ValueError:
        return None
    if duration_ms < 0:
        return None
    return ParsedHttpAccess(
        ended_at=_ts_str(line, ""),
        method=method.upper(),
        path=path,
        duration_ms=duration_ms,
        log_format="nginx_combined",
    )


def _parse_nginx_json(line: str) -> ParsedHttpAccess | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    rt = data.get("request_time") or data.get("upstream_response_time")
    method = data.get("request_method") or data.get("method")
    path = data.get("request_uri") or data.get("uri") or data.get("path")
    if rt is None or not method or not path:
        return None
    try:
        duration_ms = int(float(rt) * 1000)
    except (TypeError, ValueError):
        return None
    return ParsedHttpAccess(
        ended_at=_ts_str(line, ""),
        method=str(method).upper(),
        path=str(path),
        duration_ms=duration_ms,
        log_format="nginx_json",
    )


def _parse_iis_w3c(line: str, source_file: str) -> ParsedHttpAccess | None:
    lower = source_file.replace("\\", "/").lower()
    if "u_ex" not in lower and "w3svc" not in lower:
        return None
    if line.startswith("#"):
        return None
    parts = line.split()
    if len(parts) < 10:
        return None
    try:
        time_taken = int(parts[-1])
    except ValueError:
        return None
    if time_taken < 0:
        return None
    method = "GET"
    path = "/"
    for i, part in enumerate(parts):
        if part.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
            method = part.upper()
            if i + 1 < len(parts):
                path = parts[i + 1]
            break
    return ParsedHttpAccess(
        ended_at=_ts_str(line, source_file),
        method=method,
        path=path,
        duration_ms=time_taken,
        log_format="iis_w3c",
    )


def _parse_generic(line: str, source_file: str) -> ParsedHttpAccess | None:
    match = _RE_GENERIC_HTTP.search(line)
    if match:
        duration_ms = int(match.group(3))
        return ParsedHttpAccess(
            ended_at=_ts_str(line, source_file),
            method=match.group(1).upper(),
            path=match.group(2).strip('"'),
            duration_ms=duration_ms,
            log_format="generic_http_ms",
        )
    match = _RE_GENERIC_HTTP_SEC.search(line)
    if match:
        try:
            duration_ms = int(float(match.group(3)) * 1000)
        except ValueError:
            return None
        return ParsedHttpAccess(
            ended_at=_ts_str(line, source_file),
            method=match.group(1).upper(),
            path=match.group(2).strip('"'),
            duration_ms=duration_ms,
            log_format="generic_http_sec",
        )
    return None
