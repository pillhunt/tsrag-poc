"""Разведка формата меток времени в log-файлах."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from incident_intent.log_filter_models import LogFileInfo
from incident_intent.log_scan import resolve_log_path
from incident_intent.timestamp_parsers import detect_timestamp_format

_PROBE_LINES = 50
_TAIL_LINES = 20


def _sample_lines(path: Path, *, head: int, tail: int) -> list[str]:
    lines: list[str] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for i, raw in enumerate(handle):
                if i < head:
                    lines.append(raw.rstrip("\n\r"))
                else:
                    break
        if path.stat().st_size > 256_000 and tail > 0:
            with path.open(encoding="utf-8", errors="replace") as handle:
                all_lines = handle.readlines()
            for raw in all_lines[-tail:]:
                lines.append(raw.rstrip("\n\r"))
    except OSError:
        return []
    return lines


def probe_file_format(relative_path: str, lines: list[str]) -> str | None:
    counts: Counter[str] = Counter()
    for line in lines:
        fmt = detect_timestamp_format(line, file_path=relative_path)
        if fmt:
            counts[fmt] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def probe_log_formats(
    logs_path: str,
    log_files: list[LogFileInfo],
    *,
    logs_is_file: bool,
    lines_per_file: int = _PROBE_LINES,
) -> dict[str, str]:
    root = Path(logs_path).resolve()
    detected: dict[str, str] = {}
    for info in log_files:
        path = resolve_log_path(root, info.relative_path, logs_is_file)
        if not path.is_file():
            continue
        samples = _sample_lines(path, head=lines_per_file, tail=_TAIL_LINES)
        fmt = probe_file_format(info.relative_path, samples)
        if fmt:
            detected[info.relative_path] = fmt
    return detected


def union_detected_formats(detected: dict[str, str]) -> tuple[str, ...]:
    from incident_intent.time_pattern_factory import DEFAULT_FORMATS

    formats = set(DEFAULT_FORMATS)
    formats.update(detected.values())
    return tuple(formats)
