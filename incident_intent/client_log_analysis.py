"""
E2: разбор ClientLogs / console — события на стороне клиента.
"""

from __future__ import annotations

import re
from collections import defaultdict

from incident_intent.e_analysis_models import (
    ClientLogAnalysisRequest,
    ClientLogAnalysisResponse,
    ClientLogEvent,
)
from incident_intent.slice_file_filter import file_name_lower, filter_lines_by_file
from incident_intent.timestamp_parsers import parse_log_timestamp

_CLIENT_FILE_HINTS = ("clientlogs", "client.log", "console", "browser")
_MAX_LINE = 2000

_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "connection_reset",
        re.compile(
            r"(?i)ConnectionReset|оборвал\s+соединение|connection\s+reset|разорвано\s+соединение"
        ),
    ),
    (
        "disconnect",
        re.compile(
            r"(?i)\bdisconnect\b|отключен|разорван|connection\s+closed|client\s+disconnect"
        ),
    ),
    (
        "timeout_client",
        re.compile(
            r"(?i)(client|ui|browser|signalr).{0,40}timeout|timeout.{0,40}(client|ui|request\s+aborted)"
        ),
    ),
    (
        "signalr_websocket",
        re.compile(r"(?i)SignalR|WebSocket|hub\s+connection"),
    ),
    (
        "network_error",
        re.compile(r"(?i)network\s+error|failed\s+to\s+fetch|ERR_CONNECTION|net::ERR"),
    ),
)


def _is_client_log_file(path: str) -> bool:
    name = file_name_lower(path)
    return any(h in name for h in _CLIENT_FILE_HINTS)


def _classify_line(text: str) -> str | None:
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            return category
    return None


def _timestamp_str(text: str, *, file_path: str) -> str | None:
    dt = parse_log_timestamp(text, file_path=file_path)
    if dt:
        return dt.isoformat(sep=" ", timespec="seconds")
    return None


def _truncate(text: str) -> str:
    if len(text) <= _MAX_LINE:
        return text
    return text[:_MAX_LINE] + "…"


def _build_conclusions(by_category: dict[str, int], event_count: int) -> list[str]:
    if event_count == 0:
        return [
            "В срезе нет маркеров клиентских ошибок (ClientLogs/console) — "
            "обрывы соединения на клиенте по логам не подтверждены.",
        ]
    parts = [f"Клиентские события: {event_count} (" + ", ".join(
        f"{k}: {v}" for k, v in sorted(by_category.items(), key=lambda x: -x[1])
    ) + ")."]
    if by_category.get("connection_reset"):
        parts.append(
            "ConnectionReset/обрыв согласуется с долгим ожиданием ответа сервера, "
            "а не обязательно с «браузером как причиной»."
        )
    return parts


def analyze_client_logs(req: ClientLogAnalysisRequest) -> ClientLogAnalysisResponse:
    lines = filter_lines_by_file(req.time_window_lines, _is_client_log_file)
    if not lines:
        return ClientLogAnalysisResponse(
            status="ok",
            ran=False,
            conclusions=[
                "Файлы ClientLogs/console в срезе не найдены — клиентская сторона не анализировалась.",
            ],
        )

    files = sorted({ln.file for ln in lines})
    by_category: dict[str, int] = defaultdict(int)
    samples: list[ClientLogEvent] = []
    total = 0

    for ln in lines:
        category = _classify_line(ln.text)
        if not category:
            continue
        total += 1
        by_category[category] += 1
        if len(samples) < req.max_samples:
            samples.append(
                ClientLogEvent(
                    category=category,
                    source_file=ln.file,
                    line_number=ln.line_number,
                    timestamp=_timestamp_str(ln.text, file_path=ln.file),
                    text=_truncate(ln.text),
                )
            )

    return ClientLogAnalysisResponse(
        status="ok",
        ran=True,
        files_matched=files,
        event_count=total,
        by_category=dict(by_category),
        sample_lines=samples,
        conclusions=_build_conclusions(dict(by_category), total),
    )
