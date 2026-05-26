"""Модели скана keywords/якорей в артефактах (узкое и широкое окно)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WindowKind = Literal["narrow", "wide"]


class ArtifactScanRequest(BaseModel):
    logs_path: str = Field(min_length=1)
    incident_date: str | None = None
    time_window_start: str | None = None
    time_window_end: str | None = None
    log_search_patterns: list[str] = Field(default_factory=list)
    slow_log_search_patterns: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    time_filter_mode: Literal["time_window", "full_corpus"] = "time_window"
    time_filter_strategy: str = "auto"
    caseone_path: str | None = None
    recursive: bool = True
    max_depth: int | None = None


class WindowHitCounts(BaseModel):
    narrow: int = 0
    wide: int = 0


class ArtifactSampleLine(BaseModel):
    file: str
    line_number: int
    window: WindowKind
    matched: str
    text: str


class ArtifactScanResponse(BaseModel):
    status: Literal["ok", "error", "skipped"] = "ok"
    narrow_line_count: int = 0
    wide_line_count: int = 0
    keyword_hits: dict[str, WindowHitCounts] = Field(default_factory=dict)
    anchor_hits: dict[str, WindowHitCounts] = Field(default_factory=dict)
    discovered_anchors: list[str] = Field(default_factory=list)
    anchors_for_search: list[str] = Field(default_factory=list)
    samples: list[ArtifactSampleLine] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
