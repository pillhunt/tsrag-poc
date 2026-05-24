from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from incident_intent.log_filter_models import FilterLogsRequest, TimeWindowLine
from incident_intent.slow_requests_models import SlowRequestRow

ErrorCategory = Literal[
    "sql_deadlock",
    "sql_pk_duplicate",
    "sql_timeout",
    "concurrency",
    "connection",
    "generic_error",
    "other",
]


class CorrelateErrorsRequest(FilterLogsRequest):
    time_window_lines: list[TimeWindowLine] = Field(
        min_length=1,
        description="Срез из POST /api/filter-logs",
    )
    slow_requests: list[SlowRequestRow] = Field(
        default_factory=list,
        description="Результат шага 4 для привязки по времени",
    )
    search_keywords: list[str] = Field(default_factory=list)
    filter_by_keywords: bool = False
    global_log_only: bool = True
    include_other_error_logs: bool = Field(
        default=False,
        description="Искать Exception и в не-global файлах среза",
    )
    correlation_window_sec: int = Field(default=90, ge=0, le=3600)
    max_errors_returned: int = Field(default=100, ge=1, le=500)


class ErrorCategoryCount(BaseModel):
    category: ErrorCategory
    count: int


class ErrorInWindow(BaseModel):
    timestamp: str | None
    category: ErrorCategory
    file: str
    line_number: int
    text: str
    matched_pattern: str


class SlowRequestCorrelation(BaseModel):
    slow_request: SlowRequestRow
    related_errors: list[ErrorInWindow] = Field(default_factory=list)


class CorrelateErrorsResponse(BaseModel):
    status: Literal["ok", "error"]
    correlation_window_sec: int = 90
    global_log_only: bool = True
    errors_in_window: list[ErrorInWindow] = Field(default_factory=list)
    by_category: list[ErrorCategoryCount] = Field(default_factory=list)
    correlations: list[SlowRequestCorrelation] = Field(default_factory=list)
    unparsed_timestamp_count: int = 0
    conclusions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
