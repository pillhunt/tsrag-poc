"""Модели поиска playbook в Confluence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from incident_intent.artifact_scan_models import WindowHitCounts


class ConfluenceSearchRequest(BaseModel):
    anchors: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    investigation_goal: str = ""
    keywords: list[str] = Field(default_factory=list)


class ConfluencePageHit(BaseModel):
    page_id: str
    title: str
    score: float = 0.0
    matched_anchors: list[str] = Field(default_factory=list)
    url: str = ""


class ConfluenceSearchResponse(BaseModel):
    status: Literal["ok", "error", "skipped"] = "ok"
    configured: bool = False
    found: bool = False
    query_text: str = ""
    top_page: ConfluencePageHit | None = None
    candidates: list[ConfluencePageHit] = Field(default_factory=list)
    body_plain: str = ""
    page_anchors: list[str] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PlaybookGateRequest(BaseModel):
    confluence: ConfluenceSearchResponse
    anchors_for_search: list[str] = Field(default_factory=list)
    anchor_hits: dict[str, WindowHitCounts] = Field(default_factory=dict)


class PlaybookGateResponse(BaseModel):
    use_playbook: bool = False
    reason: str = ""
    log_anchor_hits: int = 0
    page_anchor_hits: int = 0
    shared_anchors: list[str] = Field(default_factory=list)
