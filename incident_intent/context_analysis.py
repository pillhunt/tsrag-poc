"""Запуск E1–E3 и обогащение запроса заключения."""

from __future__ import annotations

from incident_intent.caseone_config_index import index_caseone_config
from incident_intent.client_log_analysis import analyze_client_logs
from incident_intent.conclusion_models import IncidentConclusionRequest
from incident_intent.e_analysis_models import (
    CaseoneConfigIndexRequest,
    ClientLogAnalysisRequest,
    WorkflowTraceAnalysisRequest,
)
from incident_intent.workflow_trace_analysis import analyze_workflow_trace


def _analysis_lines(req: IncidentConclusionRequest) -> list:
    if req.context_time_window_lines:
        return req.context_time_window_lines
    if req.slow_time_window_lines:
        return req.slow_time_window_lines
    return req.time_window_lines or []


def enrich_conclusion_request(req: IncidentConclusionRequest) -> IncidentConclusionRequest:
    """Дополняет запрос результатами E1–E3, если они ещё не переданы."""
    lines = _analysis_lines(req)
    updates: dict = {}

    if req.workflow_trace is None and lines:
        updates["workflow_trace"] = analyze_workflow_trace(
            WorkflowTraceAnalysisRequest(time_window_lines=lines)
        )

    if req.client_logs is None and lines:
        updates["client_logs"] = analyze_client_logs(
            ClientLogAnalysisRequest(time_window_lines=lines)
        )

    caseone = (req.caseone_path or "").strip()
    if req.caseone_config is None and caseone:
        keywords = list(req.intent_table.search_keywords or [])
        updates["caseone_config"] = index_caseone_config(
            CaseoneConfigIndexRequest(
                caseone_path=caseone,
                search_keywords=keywords,
            )
        )

    if not updates:
        return req
    return req.model_copy(update=updates)
