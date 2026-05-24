from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IntentTableRequest(BaseModel):
    incident_description: str = Field(min_length=3, description="Текст описания инцидента")
    logs_path: str | None = Field(
        default=None,
        description="Путь к папке логов",
    )
    caseone_path: str | None = Field(
        default=None,
        description="Путь к caseone",
    )
    user_force_complete: bool = False


class IntentField(BaseModel):
    value: str | None
    source: Literal["user_text", "log_folder", "merged", "unknown"] = "unknown"
    note: str | None = None


class IntentTable(BaseModel):
    incident_date: IntentField
    time_window_start: IntentField
    time_window_end: IntentField
    symptoms: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(
        default_factory=list,
        description="Подстроки для grep по содержимому логов (шаг 3), из LLM",
    )
    investigation_goal: str
    optional_paths: dict[str, str | None] = Field(default_factory=dict)
    log_search_patterns: list[str] = Field(default_factory=list)
    slow_log_search_patterns: list[str] = Field(
        default_factory=list,
        description="Расширенные префиксы времени (±ч) для шагов 4–5",
    )
    min_slow_request_ms: int | None = Field(
        default=None,
        description="Порог «долгого» HTTP из жалобы (шаг 4)",
    )
    reported_duration_min_minutes: float | None = Field(
        default=None,
        description="Нижняя оценка длительности из жалобы, минуты",
    )
    reported_duration_max_minutes: float | None = Field(
        default=None,
        description="Верхняя оценка длительности из жалобы, минуты",
    )
    time_filter_mode: Literal["time_window", "full_corpus"] = "time_window"
    confidence: Literal["high", "medium", "low"] = "medium"
    missing_fields: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IntentTableResponse(BaseModel):
    status: Literal["complete", "needs_clarification"]
    table: IntentTable | None = None
    clarifying_questions: list[str] = Field(default_factory=list)
    raw_llm: dict | None = None
