"""
Поиск playbook-страниц в Confluence (CQL + совпадение якорей в теле страницы).
"""

from __future__ import annotations

import os
import re

from incident_intent.confluence_client import (
    ConfluenceClientError,
    ConfluenceNotConfigured,
    build_page_url,
    get_confluence_client,
    is_confluence_configured,
    strip_html,
)
from incident_intent.confluence_models import (
    ConfluencePageHit,
    ConfluenceSearchRequest,
    ConfluenceSearchResponse,
)
from incident_intent.keyword_utils import normalize_search_keywords

_SEARCH_LIMIT = int(os.getenv("CONFLUENCE_SEARCH_LIMIT", "10"))
_CQL_PREFIX = os.getenv("CONFLUENCE_CQL_PREFIX", "").strip()
_SPACE_KEY = os.getenv("CONFLUENCE_SPACE_KEY", "").strip()
_RE_ANCHOR_BLOCK = re.compile(
    r"(?:якор[аи]|anchors?)\s*[:=]\s*([^\n]+)",
    re.IGNORECASE,
)


def _escape_cql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_query_text(req: ConfluenceSearchRequest) -> str:
    anchors = normalize_search_keywords(req.anchors)[:15]
    parts = list(anchors)
    for s in req.symptoms[:3]:
        if s and s.strip():
            parts.append(s.strip()[:80])
    if req.investigation_goal:
        parts.append(req.investigation_goal.strip()[:120])
    text = " ".join(parts)
    return text[:500]


def _build_cql(query_text: str, anchors: list[str]) -> str:
    clauses: list[str] = ['type = "page"']
    if _SPACE_KEY:
        clauses.append(f'space = "{_escape_cql(_SPACE_KEY)}"')
    if _CQL_PREFIX:
        clauses.append(f"({_CQL_PREFIX})")
    if query_text:
        clauses.append(f'siteSearch ~ "{_escape_cql(query_text)}"')
    elif anchors:
        ors = " OR ".join(f'text ~ "{_escape_cql(a)}"' for a in anchors[:8])
        clauses.append(f"({ors})")
    return " AND ".join(clauses)


def _page_anchors_from_body(title: str, body: str) -> list[str]:
    found: list[str] = []
    for m in _RE_ANCHOR_BLOCK.finditer(body):
        chunk = m.group(1)
        for part in re.split(r"[,;|]", chunk):
            token = part.strip()
            if len(token) >= 3:
                found.append(token)
    merged = normalize_search_keywords(found + [title])
    return merged


def _anchors_in_text(anchors: list[str], haystack: str) -> list[str]:
    fold = haystack.casefold()
    return [a for a in anchors if a.casefold() in fold]


def _score_page(
    *,
    position: int,
    matched: list[str],
    query_anchors: list[str],
) -> float:
    base = max(0.0, 10.0 - position)
    return base + len(matched) * 2.0 + len(set(matched) & set(query_anchors)) * 1.5


def search_confluence_playbooks(req: ConfluenceSearchRequest) -> ConfluenceSearchResponse:
    if not is_confluence_configured():
        return ConfluenceSearchResponse(
            status="skipped",
            configured=False,
            conclusions=["Confluence не настроен (CONFLUENCE_URL пуст)."],
        )

    query_anchors = normalize_search_keywords(req.anchors)
    query_text = _build_query_text(req)

    try:
        client = get_confluence_client()
        cql = _build_cql(query_text, query_anchors)
        raw = client.cql(cql, limit=_SEARCH_LIMIT)
    except ConfluenceNotConfigured as exc:
        return ConfluenceSearchResponse(
            status="skipped",
            configured=False,
            errors=[str(exc)],
        )
    except Exception as exc:
        return ConfluenceSearchResponse(
            status="error",
            configured=True,
            query_text=query_text,
            errors=[f"Confluence API: {exc}"],
        )

    results = raw.get("results") if isinstance(raw, dict) else []
    if not isinstance(results, list):
        results = []

    hits: list[ConfluencePageHit] = []
    for pos, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        page_id = str(content.get("id") or item.get("id") or "")
        title = str(content.get("title") or item.get("title") or "")
        if not page_id:
            continue

        body_html = ""
        try:
            page = client.get_page_by_id(page_id, expand="body.storage")
            if isinstance(page, dict):
                body = page.get("body") or {}
                storage = body.get("storage") if isinstance(body, dict) else {}
                body_html = storage.get("value") if isinstance(storage, dict) else ""
                title = str(page.get("title") or title)
        except Exception:
            body_html = ""

        plain = strip_html(body_html)
        page_anchors = _page_anchors_from_body(title, plain)
        search_set = normalize_search_keywords(query_anchors + page_anchors)
        matched = _anchors_in_text(search_set, f"{title}\n{plain}")
        score = _score_page(position=pos, matched=matched, query_anchors=query_anchors)

        hits.append(
            ConfluencePageHit(
                page_id=page_id,
                title=title,
                score=score,
                matched_anchors=matched,
                url=build_page_url(page_id),
            )
        )

    hits.sort(key=lambda h: -h.score)
    top = hits[0] if hits else None
    body_plain = ""
    page_anchors: list[str] = []
    if top:
        try:
            page = client.get_page_by_id(top.page_id, expand="body.storage")
            if isinstance(page, dict):
                storage = (page.get("body") or {}).get("storage") or {}
                body_plain = strip_html(storage.get("value", ""))
                page_anchors = _page_anchors_from_body(top.title, body_plain)
        except Exception:
            pass

    conclusions: list[str] = []
    if top:
        conclusions.append(
            f"Confluence: «{top.title}» (score={top.score:.1f}, "
            f"якорей на странице: {len(top.matched_anchors)})."
        )
    else:
        conclusions.append("Confluence: страниц по запросу не найдено.")

    return ConfluenceSearchResponse(
        status="ok",
        configured=True,
        found=top is not None,
        query_text=query_text,
        top_page=top,
        candidates=hits[1:5],
        body_plain=body_plain,
        page_anchors=page_anchors,
        conclusions=conclusions,
    )
