"""Решение: отдать playbook из Confluence или полный разбор."""

from __future__ import annotations

import os

from incident_intent.artifact_scan_models import WindowHitCounts
from incident_intent.confluence_models import PlaybookGateRequest, PlaybookGateResponse
from incident_intent.keyword_utils import normalize_search_keywords

_LOG_ANCHOR_MIN = int(os.getenv("LOG_ANCHOR_MIN", "2"))
_PAGE_ANCHOR_MIN = int(os.getenv("CONFLUENCE_PAGE_ANCHOR_MIN", "2"))
_SCORE_MIN = float(os.getenv("CONFLUENCE_SCORE_MIN", "4"))


def _log_hit_total(anchor_hits: dict[str, WindowHitCounts], anchors: list[str]) -> int:
    count = 0
    for a in anchors:
        stats = anchor_hits.get(a)
        if not stats:
            continue
        if stats.narrow + stats.wide > 0:
            count += 1
    return count


def evaluate_playbook_gate(req: PlaybookGateRequest) -> PlaybookGateResponse:
    conf = req.confluence
    if conf.status == "skipped" or not conf.configured:
        return PlaybookGateResponse(
            use_playbook=False,
            reason="Confluence не настроен — только полный разбор.",
        )
    if conf.status == "error":
        return PlaybookGateResponse(
            use_playbook=False,
            reason="Ошибка Confluence — полный разбор.",
        )
    if not conf.found or conf.top_page is None:
        return PlaybookGateResponse(
            use_playbook=False,
            reason="В Confluence не найдена подходящая статья.",
        )

    page = conf.top_page
    page_anchors = normalize_search_keywords(
        conf.page_anchors + page.matched_anchors + req.anchors_for_search
    )
    search_anchors = normalize_search_keywords(req.anchors_for_search)

    page_hits = [a for a in page_anchors if a.casefold() in (conf.body_plain + page.title).casefold()]
    if not page_hits:
        page_hits = list(page.matched_anchors)

    log_hits = _log_hit_total(req.anchor_hits, page_anchors)
    shared = [
        a
        for a in page_anchors
        if req.anchor_hits.get(a) is not None
        and req.anchor_hits[a].narrow + req.anchor_hits[a].wide > 0
    ]
    if not shared:
        shared = [a for a in search_anchors if a in page.matched_anchors]

    if page.score < _SCORE_MIN and len(page.matched_anchors) < _PAGE_ANCHOR_MIN:
        return PlaybookGateResponse(
            use_playbook=False,
            reason=(
                f"Низкий score Confluence ({page.score:.1f}) и мало якорей на странице."
            ),
            log_anchor_hits=log_hits,
            page_anchor_hits=len(page_hits),
            shared_anchors=shared,
        )

    if log_hits < _LOG_ANCHOR_MIN:
        return PlaybookGateResponse(
            use_playbook=False,
            reason=(
                f"Логи не подтверждают playbook: якорей в логах {log_hits} "
                f"(нужно ≥ {_LOG_ANCHOR_MIN})."
            ),
            log_anchor_hits=log_hits,
            page_anchor_hits=len(page_hits),
            shared_anchors=shared,
        )

    if not shared:
        return PlaybookGateResponse(
            use_playbook=False,
            reason="Нет общих якорей между статьёй Confluence и логами.",
            log_anchor_hits=log_hits,
            page_anchor_hits=len(page_hits),
        )

    return PlaybookGateResponse(
        use_playbook=True,
        reason=(
            f"Playbook: «{page.title}»; общих якорей с логами: {len(shared)}."
        ),
        log_anchor_hits=log_hits,
        page_anchor_hits=len(page_hits),
        shared_anchors=shared,
    )
