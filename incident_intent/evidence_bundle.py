"""Сжатое досье для LLM (шаг 6) из результатов шагов 0–5."""

from __future__ import annotations

from typing import Any

from incident_intent.conclusion_models import FilterSummary, IncidentConclusionRequest
from incident_intent.models import IntentTable


def _intent_payload(table: IntentTable) -> dict[str, Any]:
    return {
        "incident_date": table.incident_date.value,
        "time_window": {
            "start": table.time_window_start.value,
            "end": table.time_window_end.value,
        },
        "symptoms": table.symptoms,
        "search_keywords": table.search_keywords,
        "anchors": table.anchors,
        "investigation_goal": table.investigation_goal,
        "min_slow_request_ms": table.min_slow_request_ms,
        "reported_duration_min_minutes": table.reported_duration_min_minutes,
        "reported_duration_max_minutes": table.reported_duration_max_minutes,
        "slow_log_search_patterns": table.slow_log_search_patterns,
        "input_confidence": table.confidence,
        "notes": table.notes,
    }


def _trim_samples(
    lines: list[dict[str, Any]],
    *,
    limit: int,
    budget: list[int],
) -> list[dict[str, Any]]:
    if limit <= 0 or budget[0] <= 0:
        return []
    out: list[dict[str, Any]] = []
    for item in lines[:limit]:
        if budget[0] <= 0:
            break
        text = str(item.get("text", ""))
        if len(text) > 500:
            item = {**item, "text": text[:500] + "…"}
        out.append(item)
        budget[0] -= 1
    return out


def build_evidence_payload(req: IncidentConclusionRequest) -> dict[str, Any]:
    budget = [req.max_evidence_samples]
    fs = req.filter_summary

    payload: dict[str, Any] = {
        "step0_intent": _intent_payload(req.intent_table),
        "step1_2_slice": {
            "ran": fs.time_window_line_count > 0 or fs.total_matching_lines > 0,
            "time_filter_mode": getattr(req.intent_table, "time_filter_mode", "time_window"),
            "patterns_used": fs.patterns_used,
            "slow_patterns_used": fs.slow_patterns_used,
            "total_lines_in_time_window": fs.total_matching_lines,
            "lines_in_passed_slice": fs.time_window_line_count,
            "slow_lines_in_passed_slice": fs.slow_time_window_line_count,
            "truncated": fs.time_window_truncated,
            "slow_truncated": fs.slow_time_window_truncated,
            "files_in_window": fs.files_in_window[:30],
        },
        "step3_keywords": {"ran": False},
        "step4_slow_requests": {"ran": False},
        "step5_errors": {"ran": False},
        "step_workflow_trace": {"ran": False},
        "step_client_logs": {"ran": False},
        "step_caseone_config": {"ran": False},
        "artifact_scan": {"ran": False},
        "confluence": {"ran": False},
    }

    if req.artifact_scan and req.artifact_scan.status == "ok":
        sc = req.artifact_scan
        payload["artifact_scan"] = {
            "ran": True,
            "narrow_line_count": sc.narrow_line_count,
            "wide_line_count": sc.wide_line_count,
            "anchors_for_search": sc.anchors_for_search[:25],
            "discovered_anchors": sc.discovered_anchors[:25],
            "keyword_hit_count": len(sc.keyword_hits),
            "anchor_hit_count": len(sc.anchor_hits),
            "prior_conclusions": sc.conclusions,
        }

    if req.confluence_search and req.confluence_search.status == "ok":
        cf = req.confluence_search
        top = cf.top_page
        payload["confluence"] = {
            "ran": True,
            "found": cf.found,
            "query_text": cf.query_text[:300],
            "top_title": top.title if top else None,
            "top_score": top.score if top else None,
            "matched_anchors": top.matched_anchors[:15] if top else [],
            "prior_conclusions": cf.conclusions,
        }
    elif req.confluence_search and req.confluence_search.status == "skipped":
        payload["confluence"] = {
            "ran": False,
            "skipped": True,
            "prior_conclusions": req.confluence_search.conclusions,
        }

    if req.symptom_search and req.symptom_search.status == "ok":
        s3 = req.symptom_search
        samples = [
            {
                "file": s.file,
                "line": s.line_number,
                "matched_keyword": s.matched_keyword,
                "text": s.text,
            }
            for s in s3.sample_lines
        ]
        payload["step3_keywords"] = {
            "ran": True,
            "search_keywords_used": s3.search_keywords_used,
            "total_matching_lines": s3.total_matching_lines,
            "by_file": [
                {"file": f.relative_path, "matches": f.match_count}
                for f in s3.by_file[:15]
            ],
            "prior_conclusions": s3.conclusions,
            "sample_lines": _trim_samples(samples, limit=10, budget=budget),
        }

    if req.slow_requests and req.slow_requests.status == "ok":
        s4 = req.slow_requests
        payload["step4_slow_requests"] = {
            "ran": True,
            "min_duration_ms": s4.min_duration_ms,
            "slow_request_count": len(s4.slow_requests),
            "top_requests": [
                {
                    "ended_at": r.ended_at,
                    "method": r.method,
                    "path": r.path,
                    "duration_min": r.duration_min,
                    "duration_ms": r.duration_ms,
                    "log_format": r.log_format,
                }
                for r in s4.slow_requests[:15]
            ],
            "parsed_by_format": s4.parsed_by_format,
            "by_path": [
                {
                    "path": p.path,
                    "count": p.count,
                    "max_duration_min": p.max_duration_min,
                }
                for p in s4.by_path[:10]
            ],
            "prior_conclusions": s4.conclusions,
        }

    if req.error_correlation and req.error_correlation.status == "ok":
        s5 = req.error_correlation
        samples = [
            {
                "time": e.timestamp,
                "engine": e.error_engine,
                "category": e.category,
                "file": e.file,
                "line": e.line_number,
                "pattern": e.matched_pattern,
                "text": e.text,
            }
            for e in s5.errors_in_window[:10]
        ]
        payload["step5_errors"] = {
            "ran": True,
            "correlation_window_sec": s5.correlation_window_sec,
            "global_log_only": s5.global_log_only,
            "error_count": len(s5.errors_in_window),
            "by_category": [
                {"category": c.category, "count": c.count} for c in s5.by_category
            ],
            "by_engine": [
                {"engine": c.engine, "count": c.count} for c in s5.by_engine
            ],
            "correlations": [
                {
                    "slow_request": {
                        "ended_at": c.slow_request.ended_at,
                        "method": c.slow_request.method,
                        "path": c.slow_request.path,
                        "duration_min": c.slow_request.duration_min,
                    },
                    "related_error_count": len(c.related_errors),
                    "related_errors": [
                        {
                            "time": e.timestamp,
                            "category": e.category,
                            "pattern": e.matched_pattern,
                        }
                        for e in c.related_errors[:5]
                    ],
                }
                for c in s5.correlations[:10]
            ],
            "prior_conclusions": s5.conclusions,
            "sample_errors": _trim_samples(samples, limit=10, budget=budget),
        }

    wt = req.workflow_trace
    if wt and wt.status == "ok":
        payload["step_workflow_trace"] = {
            "ran": wt.ran,
            "files_matched": wt.files_matched[:10],
            "line_count": wt.line_count,
            "paired_operations": [
                {
                    "label": p.label,
                    "begin_at": p.begin_at,
                    "end_at": p.end_at,
                    "duration_sec": p.duration_sec,
                }
                for p in wt.paired_operations[:15]
            ],
            "anomalies": wt.anomalies[:10],
            "prior_conclusions": wt.conclusions,
        }

    cl = req.client_logs
    if cl and cl.status == "ok":
        cl_samples = [
            {
                "category": e.category,
                "file": e.source_file,
                "line": e.line_number,
                "time": e.timestamp,
                "text": e.text,
            }
            for e in cl.sample_lines
        ]
        payload["step_client_logs"] = {
            "ran": cl.ran,
            "event_count": cl.event_count,
            "by_category": cl.by_category,
            "prior_conclusions": cl.conclusions,
            "sample_lines": _trim_samples(cl_samples, limit=8, budget=budget),
        }

    cc = req.caseone_config
    if cc and cc.status == "ok":
        payload["step_caseone_config"] = {
            "ran": cc.ran,
            "caseone_path": cc.caseone_path,
            "files_scanned": cc.files_scanned,
            "snippets": [
                {
                    "file": s.file,
                    "key": s.key_path,
                    "value": s.value,
                }
                for s in cc.snippets[:15]
            ],
            "prior_conclusions": cc.conclusions,
        }

    return payload
