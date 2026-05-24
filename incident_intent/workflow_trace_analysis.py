"""
E1: разбор WorkflowTrace.log — пары начало/конец операций на клиенте.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime

from incident_intent.e_analysis_models import (
    PairedWorkflowOperation,
    WorkflowStepEvent,
    WorkflowTraceAnalysisRequest,
    WorkflowTraceAnalysisResponse,
)
from incident_intent.log_filter_models import TimeWindowLine
from incident_intent.slice_file_filter import file_name_lower, filter_lines_by_file
from incident_intent.timestamp_parsers import parse_log_timestamp

_RE_JSON_MESSAGE = re.compile(r'"message"\s*:\s*"([^"]+)"', re.IGNORECASE)
_RE_JSON_OPERATION = re.compile(r'"operation(?:Name)?"\s*:\s*"([^"]+)"', re.IGNORECASE)
_RE_QUOTED = re.compile(r'"([^"]{3,120})"')

_BEGIN_PATTERNS = (
    re.compile(r"(?i)начало\s+сохран"),
    re.compile(r"(?i)workflow[^a-z0-9]*begin"),
    re.compile(r"(?i)\bbegin\b.*(?:save|сохран|workflow)"),
)
_END_PATTERNS = (
    re.compile(r"(?i)конец\s+сохран"),
    re.compile(r"(?i)\"конец\""),
    re.compile(r"(?i)(?:^|[\s;])конец(?:\s|$|[;\"])"),
    re.compile(r"(?i)workflow[^a-z0-9]*end"),
    re.compile(r"(?i)\bend\b.*(?:save|сохран|workflow)"),
)


def _is_workflow_trace_file(path: str) -> bool:
    return "workflowtrace" in file_name_lower(path)


def _detect_kind(text: str) -> str | None:
    for pat in _BEGIN_PATTERNS:
        if pat.search(text):
            return "begin"
    for pat in _END_PATTERNS:
        if pat.search(text):
            return "end"
    return None


def _extract_label(text: str, kind: str) -> str:
    for pat in (_RE_JSON_OPERATION, _RE_JSON_MESSAGE):
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    for m in _RE_QUOTED.finditer(text):
        q = m.group(1).strip()
        low = q.lower()
        if low in ("конец", "end", "begin", "start"):
            continue
        if "начало" in low or "конец" in low:
            if len(q) > 40:
                continue
        return q
    if kind == "begin" and re.search(r"(?i)начало\s+сохран", text):
        return "сохранение"
    if kind == "end" and re.search(r"(?i)конец", text):
        return "сохранение"
    return "операция"


def _normalize_label(label: str) -> str:
    low = re.sub(r"\s+", " ", label.strip().lower())[:120]
    if "начало" in low and "сохран" in low:
        return "сохранение"
    if low in ("конец", "end") or ("конец" in low and "сохран" in low):
        return "сохранение"
    if low.startswith("конец") and len(low) < 30:
        return "сохранение"
    return low


def _timestamp_str(text: str, *, file_path: str) -> str | None:
    dt = parse_log_timestamp(text, file_path=file_path)
    if dt:
        return dt.isoformat(sep=" ", timespec="seconds")
    m = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", text)
    if m:
        return m.group(0).replace("T", " ")
    return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("T", " ", 1))
    except ValueError:
        return None


def _pair_operations(
    events: list[WorkflowStepEvent],
    *,
    long_step_sec: float,
) -> tuple[list[PairedWorkflowOperation], list[str]]:
    pending: dict[str, list[WorkflowStepEvent]] = defaultdict(list)
    paired: list[PairedWorkflowOperation] = []
    anomalies: list[str] = []

    for ev in events:
        key = _normalize_label(ev.label)
        if ev.kind == "begin":
            pending[key].append(ev)
            continue
        if ev.kind != "end":
            continue
        if not pending[key]:
            anomalies.append(
                f"Конец без начала: «{ev.label}» ({ev.source_file}:{ev.line_number})"
            )
            paired.append(
                PairedWorkflowOperation(
                    label=ev.label,
                    begin_at=None,
                    end_at=ev.timestamp,
                    duration_sec=None,
                )
            )
            continue
        begin_ev = pending[key].pop(0)
        begin_dt = _parse_dt(begin_ev.timestamp)
        end_dt = _parse_dt(ev.timestamp)
        duration: float | None = None
        if begin_dt and end_dt:
            duration = max(0.0, (end_dt - begin_dt).total_seconds())
        pair = PairedWorkflowOperation(
            label=begin_ev.label or ev.label,
            begin_at=begin_ev.timestamp,
            end_at=ev.timestamp,
            duration_sec=duration,
        )
        paired.append(pair)
        if duration is not None and duration > long_step_sec:
            anomalies.append(
                f"Долгий этап на клиенте ({duration:.1f} с): «{pair.label}»"
            )

    for key, stack in pending.items():
        for ev in stack:
            anomalies.append(
                f"Начало без конца: «{ev.label}» ({ev.source_file}:{ev.line_number})"
            )
            paired.append(
                PairedWorkflowOperation(
                    label=ev.label,
                    begin_at=ev.timestamp,
                    end_at=None,
                    duration_sec=None,
                )
            )

    return paired, anomalies


def _build_conclusions(
    paired: list[PairedWorkflowOperation],
    *,
    long_step_sec: float,
    line_count: int,
) -> list[str]:
    if line_count == 0:
        return [
            "В срезе нет строк WorkflowTrace.log — этапы workflow на клиенте не анализировались.",
        ]
    if not paired:
        return [
            f"В WorkflowTrace ({line_count} строк) не найдено пар начало/конец.",
        ]
    with_duration = [p for p in paired if p.duration_sec is not None]
    if not with_duration:
        return [
            f"WorkflowTrace: {len(paired)} операций без вычисленной длительности (нет меток времени).",
        ]
    fast = [p for p in with_duration if p.duration_sec is not None and p.duration_sec <= long_step_sec]
    slow = [p for p in with_duration if p.duration_sec is not None and p.duration_sec > long_step_sec]
    out = [
        f"WorkflowTrace: {len(paired)} операций, {len(with_duration)} с длительностью "
        f"(порог «долго на клиенте» {long_step_sec:g} с).",
    ]
    if fast:
        d = fast[0].duration_sec
        out.append(
            f"Быстрые этапы на клиенте (≤{long_step_sec:g} с), напр. «{fast[0].label}» — {d:.1f} с."
        )
    if slow:
        d = slow[0].duration_sec
        out.append(
            f"Долгие этапы на клиенте (>{long_step_sec:g} с), напр. «{slow[0].label}» — {d:.1f} с; "
            "сверьте с долгими HTTP на сервере (шаг 4)."
        )
    if fast and not slow:
        out.append(
            "Клиентские этапы в trace короткие — долгая жалоба может быть на сервере/SQL, не в UI."
        )
    return out


def analyze_workflow_trace(
    req: WorkflowTraceAnalysisRequest,
) -> WorkflowTraceAnalysisResponse:
    long_sec = float(
        os.getenv("POC_WORKFLOW_LONG_SEC", str(req.long_step_sec))
    )
    lines = filter_lines_by_file(req.time_window_lines, _is_workflow_trace_file)
    if not lines:
        return WorkflowTraceAnalysisResponse(
            status="ok",
            ran=False,
            line_count=0,
            conclusions=[
                "Файлы WorkflowTrace в срезе не найдены — отдельный разбор workflow не выполнялся.",
            ],
        )

    files = sorted({ln.file for ln in lines})
    events: list[WorkflowStepEvent] = []

    for ln in lines:
        kind = _detect_kind(ln.text)
        if not kind:
            continue
        label = _extract_label(ln.text, kind)
        events.append(
            WorkflowStepEvent(
                timestamp=_timestamp_str(ln.text, file_path=ln.file),
                kind=kind,  # type: ignore[arg-type]
                label=label,
                source_file=ln.file,
                line_number=ln.line_number,
            )
        )

    paired, anomalies = _pair_operations(events, long_step_sec=long_sec)
    conclusions = _build_conclusions(paired, long_step_sec=long_sec, line_count=len(lines))

    return WorkflowTraceAnalysisResponse(
        status="ok",
        ran=True,
        files_matched=files,
        line_count=len(lines),
        events=events[:100],
        paired_operations=paired[:50],
        anomalies=anomalies[:30],
        conclusions=conclusions,
    )
