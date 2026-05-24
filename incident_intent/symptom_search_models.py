from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from incident_intent.log_filter_models import FilterLogsRequest, SourcesCheck, TimeWindowLine


class SymptomSearchRequest(FilterLogsRequest):
    time_window_lines: list[TimeWindowLine] = Field(
        min_length=1,
        description="Срез строк из POST /api/filter-logs (шаги 1–2)",
    )
    search_keywords: list[str] = Field(
        min_length=1,
        description="Ключевые слова из таблицы намерений (шаг 0)",
    )
    extra_keywords: list[str] = Field(
        default_factory=list,
        description="Дополнительные подстроки от инженера",
    )


class SymptomFileStats(BaseModel):
    relative_path: str
    match_count: int
    priority: bool = False


class SymptomSampleLine(BaseModel):
    file: str
    line_number: int
    text: str
    matched_keyword: str


class SymptomSearchResponse(BaseModel):
    status: Literal["ok", "error"]
    sources: SourcesCheck | None = None
    time_patterns_used: list[str] = Field(default_factory=list)
    search_keywords_used: list[str] = Field(default_factory=list)
    total_matching_lines: int = 0
    by_file: list[SymptomFileStats] = Field(default_factory=list)
    sample_lines: list[SymptomSampleLine] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
