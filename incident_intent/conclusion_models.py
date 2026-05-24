from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from incident_intent.error_correlation_models import CorrelateErrorsResponse
from incident_intent.models import IntentTable
from incident_intent.slow_requests_models import SlowRequestsResponse
from incident_intent.symptom_search_models import SymptomSearchResponse


class FilterSummary(BaseModel):
    total_matching_lines: int = 0
    time_window_line_count: int = 0
    time_window_truncated: bool = False
    slow_time_window_line_count: int = 0
    slow_time_window_truncated: bool = False
    files_in_window: list[str] = Field(default_factory=list)
    patterns_used: list[str] = Field(default_factory=list)
    slow_patterns_used: list[str] = Field(default_factory=list)
    time_filter_mode: Literal["time_window", "full_corpus"] = "time_window"


class IncidentConclusionRequest(BaseModel):
    intent_table: IntentTable
    filter_summary: FilterSummary
    symptom_search: SymptomSearchResponse | None = None
    slow_requests: SlowRequestsResponse | None = None
    error_correlation: CorrelateErrorsResponse | None = None
    max_evidence_samples: int = Field(default=20, ge=0, le=50)


class IncidentConclusionResponse(BaseModel):
    status: Literal["ok", "error"]
    conclusion_markdown: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    confidence_reason: str = ""
    supported_by: list[str] = Field(default_factory=list)
    not_proven: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    raw_llm: dict | None = None
    errors: list[str] = Field(default_factory=list)
