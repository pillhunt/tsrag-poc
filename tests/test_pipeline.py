"""Tests for incident pipeline orchestrator."""

import tempfile
from pathlib import Path

from incident_intent.log_filter_models import FilterLogsRequest
from incident_intent.log_filter import filter_logs
from incident_intent.models import IntentField, IntentTable
from incident_intent.pipeline import PIPELINE_STEP_DEFS, run_pipeline_sync, step_title
from incident_intent.pipeline_models import PipelineRequest


def _minimal_table() -> IntentTable:
    return IntentTable(
        incident_date=IntentField(value="2026-04-23", source="user_text"),
        time_window_start=IntentField(value="01:00", source="user_text"),
        time_window_end=IntentField(value="02:00", source="user_text"),
        symptoms=["тест"],
        search_keywords=["timeout", "500"],
        investigation_goal="тест",
        log_search_patterns=["2026-04-23 01:", "2026-04-23 02:"],
    )


def test_step_titles_numbered():
    assert PIPELINE_STEP_DEFS[0].number == 1
    assert step_title(1, "x").startswith("Шаг 1.")


def test_pipeline_on_temp_logs():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        log = root / "global.log"
        log.write_text(
            "WARN | 1 | 2026-04-23 01:30:00.0 | timeout error\n"
            "WARN | 2 | 2026-04-23 01:45:00.0 | Internal Server Error 500\n",
            encoding="utf-8",
        )
        req = PipelineRequest(
            intent_table=_minimal_table(),
            logs_path=str(root),
        )
        resp = run_pipeline_sync(req)
        assert len(resp.steps) == 10
        assert resp.steps[0].step_id == "filter"
        assert resp.steps[1].step_id == "artifact_scan"
        assert resp.artifact_scan is not None
        assert resp.confluence_search is not None
        assert resp.playbook_gate is not None
        assert resp.use_playbook is False
        assert resp.filter is not None
        assert resp.filter_summary is not None
        assert resp.filter_summary.time_window_line_count >= 1


def test_filter_step_integration():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "app"
        root.mkdir()
        (root / "global.log").write_text("2026-04-23 01:00:00 err\n", encoding="utf-8")
        table = _minimal_table()
        r = filter_logs(
            FilterLogsRequest(
                logs_path=str(root.parent),
                log_search_patterns=table.log_search_patterns,
                incident_date="2026-04-23",
                time_window_start="01:00",
                time_window_end="02:00",
                time_filter_strategy="auto",
            )
        )
        assert r.total_matching_lines >= 1
