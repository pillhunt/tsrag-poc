"""Модели шагов E1–E3 (контекст перед заключением)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from incident_intent.log_filter_models import TimeWindowLine


class WorkflowStepEvent(BaseModel):
    timestamp: str | None = None
    kind: Literal["begin", "end", "message"] = "message"
    label: str = ""
    source_file: str = ""
    line_number: int = 0


class PairedWorkflowOperation(BaseModel):
    label: str
    begin_at: str | None = None
    end_at: str | None = None
    duration_sec: float | None = None


class WorkflowTraceAnalysisRequest(BaseModel):
    time_window_lines: list[TimeWindowLine] = Field(default_factory=list)
    long_step_sec: float = Field(default=30.0, ge=0.1, le=86400)


class WorkflowTraceAnalysisResponse(BaseModel):
    status: Literal["ok", "error"] = "ok"
    ran: bool = False
    files_matched: list[str] = Field(default_factory=list)
    line_count: int = 0
    events: list[WorkflowStepEvent] = Field(default_factory=list)
    paired_operations: list[PairedWorkflowOperation] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ClientLogEvent(BaseModel):
    category: str
    source_file: str
    line_number: int
    timestamp: str | None = None
    text: str = ""


class ClientLogAnalysisRequest(BaseModel):
    time_window_lines: list[TimeWindowLine] = Field(default_factory=list)
    max_samples: int = Field(default=15, ge=0, le=50)


class ClientLogAnalysisResponse(BaseModel):
    status: Literal["ok", "error"] = "ok"
    ran: bool = False
    files_matched: list[str] = Field(default_factory=list)
    event_count: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    sample_lines: list[ClientLogEvent] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CaseoneConfigSnippet(BaseModel):
    file: str
    key_path: str
    value: str
    score: int = 0


class CaseoneConfigIndexRequest(BaseModel):
    caseone_path: str = Field(min_length=1)
    search_keywords: list[str] = Field(default_factory=list)
    max_snippets: int = Field(default=20, ge=0, le=50)


class CaseoneConfigIndexResponse(BaseModel):
    status: Literal["ok", "error"] = "ok"
    ran: bool = False
    caseone_path: str = ""
    files_scanned: int = 0
    snippets: list[CaseoneConfigSnippet] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
