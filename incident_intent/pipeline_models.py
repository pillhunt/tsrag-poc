"""Модели оркестратора пайплайна (шаги 1–N)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from incident_intent.conclusion_models import FilterSummary, IncidentConclusionResponse
from incident_intent.e_analysis_models import (
    CaseoneConfigIndexResponse,
    ClientLogAnalysisResponse,
    WorkflowTraceAnalysisResponse,
)
from incident_intent.error_correlation_models import CorrelateErrorsResponse
from incident_intent.log_filter_models import FilterLogsResponse
from incident_intent.models import IntentTable
from incident_intent.slow_requests_models import SlowRequestsResponse
from incident_intent.symptom_search_models import SymptomSearchResponse

PipelineStepStatus = Literal["ok", "skipped", "error"]


class PipelineStepLog(BaseModel):
    step_number: int
    step_id: str
    title: str
    status: PipelineStepStatus = "ok"
    summary_lines: list[str] = Field(default_factory=list)


class PipelineRequest(BaseModel):
    intent_table: IntentTable
    logs_path: str = Field(min_length=1)
    caseone_path: str | None = None
    incident_id: str | None = None


class PipelineResponse(BaseModel):
    status: Literal["ok", "partial", "error"] = "ok"
    steps: list[PipelineStepLog] = Field(default_factory=list)
    filter_summary: FilterSummary | None = None
    filter: FilterLogsResponse | None = None
    symptom_search: SymptomSearchResponse | None = None
    slow_requests: SlowRequestsResponse | None = None
    error_correlation: CorrelateErrorsResponse | None = None
    workflow_trace: WorkflowTraceAnalysisResponse | None = None
    client_logs: ClientLogAnalysisResponse | None = None
    caseone_config: CaseoneConfigIndexResponse | None = None
    conclusion: IncidentConclusionResponse | None = None
    errors: list[str] = Field(default_factory=list)
