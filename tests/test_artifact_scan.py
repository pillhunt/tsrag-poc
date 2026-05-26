"""Tests for artifact scan (narrow/wide windows)."""

import tempfile
from pathlib import Path

from incident_intent.artifact_scan import scan_artifacts
from incident_intent.artifact_scan_models import ArtifactScanRequest


def test_anchor_in_wide_window_only():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        log = root / "global.log"
        log.write_text(
            "WARN | 1 | 2026-04-23 00:45:00.0 | PUT /api/ProjectTypes/PutProjectType early\n"
            "WARN | 2 | 2026-04-23 01:30:00.0 | timeout generic\n",
            encoding="utf-8",
        )
        resp = scan_artifacts(
            ArtifactScanRequest(
                logs_path=str(root),
                incident_date="2026-04-23",
                time_window_start="01:00",
                time_window_end="02:00",
                log_search_patterns=["2026-04-23 01:", "2026-04-23 00:"],
                search_keywords=["timeout"],
                anchors=["PutProjectType"],
            )
        )
        assert resp.status == "ok"
        assert resp.narrow_line_count >= 1
        assert "/api/ProjectTypes/PutProjectType" in resp.discovered_anchors or any(
            "PutProjectType" in a for a in resp.anchors_for_search
        )
        kw = resp.keyword_hits.get("timeout")
        assert kw is not None and kw.narrow >= 1


def test_playbook_gate_import():
    from incident_intent.confluence_models import ConfluenceSearchResponse, PlaybookGateRequest
    from incident_intent.playbook_gate import evaluate_playbook_gate

    gate = evaluate_playbook_gate(
        PlaybookGateRequest(
            confluence=ConfluenceSearchResponse(status="skipped", configured=False),
            anchors_for_search=["a"],
            anchor_hits={},
        )
    )
    assert gate.use_playbook is False
