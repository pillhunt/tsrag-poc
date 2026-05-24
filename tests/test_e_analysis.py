"""Tests for E1–E3 context analysis."""

from pathlib import Path

from incident_intent.caseone_config_index import index_caseone_config
from incident_intent.client_log_analysis import analyze_client_logs
from incident_intent.e_analysis_models import (
    CaseoneConfigIndexRequest,
    ClientLogAnalysisRequest,
    WorkflowTraceAnalysisRequest,
)
from incident_intent.log_filter_models import TimeWindowLine
from incident_intent.workflow_trace_analysis import analyze_workflow_trace


def _line(file: str, text: str, n: int = 1) -> TimeWindowLine:
    return TimeWindowLine(file=file, line_number=n, text=text)


def test_workflow_trace_pairs_save():
    lines = [
        _line(
            "app/WorkflowTrace.log",
            '2026-04-23 20:18:01.123 INFO "начало сохранения" projectType',
            1,
        ),
        _line(
            "app/WorkflowTrace.log",
            '2026-04-23 20:18:03.456 INFO "конец" projectType',
            2,
        ),
        _line("app/global.log", "unrelated line", 3),
    ]
    result = analyze_workflow_trace(
        WorkflowTraceAnalysisRequest(time_window_lines=lines, long_step_sec=30)
    )
    assert result.ran is True
    assert len(result.paired_operations) == 1
    assert result.paired_operations[0].duration_sec is not None
    assert 1.0 < result.paired_operations[0].duration_sec < 5.0


def test_workflow_trace_long_step_anomaly():
    lines = [
        _line(
            "WorkflowTrace.log",
            "2026-04-23 20:00:00 начало сохранения",
            1,
        ),
        _line(
            "WorkflowTrace.log",
            "2026-04-23 20:01:00 конец сохранения",
            2,
        ),
    ]
    result = analyze_workflow_trace(
        WorkflowTraceAnalysisRequest(time_window_lines=lines, long_step_sec=30)
    )
    assert any("Долгий этап" in a for a in result.anomalies)


def test_client_logs_connection_reset():
    lines = [
        _line(
            "ClientLogs.log",
            "2026-04-23 20:35:00 System.IO.IOException ConnectionResetException",
            1,
        ),
    ]
    result = analyze_client_logs(ClientLogAnalysisRequest(time_window_lines=lines))
    assert result.ran is True
    assert result.event_count == 1
    assert result.by_category.get("connection_reset") == 1


def test_caseone_config_index_masks_secret(tmp_path: Path):
    cfg = tmp_path / "appsettings.json"
    cfg.write_text(
        '{"Logging":{"LogLevel":"Warning"},'
        '"ConnectionStrings":{"Default":"Server=x;Password=secret123"},'
        '"Kestrel":{"Limits":{"MaxRequestBodySize":1048576}}}',
        encoding="utf-8",
    )
    result = index_caseone_config(
        CaseoneConfigIndexRequest(
            caseone_path=str(tmp_path),
            search_keywords=["Kestrel", "Timeout"],
        )
    )
    assert result.ran is True
    values = [s.value for s in result.snippets]
    assert all("secret123" not in v for v in values)
    assert any("Kestrel" in s.key_path or "Kestrel" in s.value for s in result.snippets) or result.files_scanned == 1
