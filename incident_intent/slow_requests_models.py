from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from incident_intent.log_filter_models import FilterLogsRequest, SourcesCheck, TimeWindowLine


class SlowRequestsRequest(FilterLogsRequest):
    log_search_patterns: list[str] = Field(min_length=1)
    time_window_lines: list[TimeWindowLine] = Field(
        min_length=1,
        description="Срез строк из POST /api/filter-logs (шаги 1–2)",
    )
    search_keywords: list[str] = Field(default_factory=list)
    min_duration_ms: int = Field(
        default=300_000,
        ge=0,
        description="Минимальная длительность запроса (по умолчанию 5 мин)",
    )
    top_n: int = Field(default=25, ge=1, le=200)
    filter_by_keywords: bool = Field(
        default=False,
        description="Только запросы, где path/строка совпадает с search_keywords",
    )
    http_access_only: bool = Field(
        default=False,
        description="Только строки, распознанные как HTTP/access (любой формат)",
    )
    middleware_only: bool | None = Field(
        default=None,
        description="Устарело: true → http_access_only",
    )


class SlowRequestRow(BaseModel):
    ended_at: str | None
    method: str
    path: str
    duration_ms: int
    duration_min: float
    source_file: str
    line_number: int
    matched_keyword: str | None = None
    log_format: str | None = None


class SlowRequestPathStats(BaseModel):
    path: str
    count: int
    max_duration_ms: int
    max_duration_min: float
    avg_duration_ms: int


class SlowRequestsResponse(BaseModel):
    status: Literal["ok", "error"]
    sources: SourcesCheck | None = None
    time_patterns_used: list[str] = Field(default_factory=list)
    min_duration_ms: int = 300_000
    filter_by_keywords: bool = False
    http_access_only: bool = False
    access_files_scanned: list[str] = Field(default_factory=list)
    parsed_by_format: dict[str, int] = Field(default_factory=dict)
    parsed_line_count: int = 0
    unparsed_in_window: int = 0
    slow_requests: list[SlowRequestRow] = Field(default_factory=list)
    by_path: list[SlowRequestPathStats] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
