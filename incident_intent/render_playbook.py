"""Сборка markdown-заключения из страницы Confluence и цитат логов."""

from __future__ import annotations

from incident_intent.artifact_scan_models import ArtifactScanResponse, ArtifactSampleLine
from incident_intent.conclusion_models import IncidentConclusionResponse
from incident_intent.confluence_models import ConfluenceSearchResponse


def _pick_citation_samples(
    scan: ArtifactScanResponse,
    shared_anchors: list[str],
    *,
    max_items: int = 5,
) -> list[ArtifactSampleLine]:
    if not scan.samples:
        return []
    shared_fold = {a.casefold() for a in shared_anchors}
    narrow = [
        s
        for s in scan.samples
        if s.window == "narrow" and s.matched.casefold() in shared_fold
    ]
    wide = [
        s
        for s in scan.samples
        if s.window == "wide" and s.matched.casefold() in shared_fold
    ]
    ordered = narrow + [s for s in wide if s not in narrow]
    if not ordered:
        ordered = list(scan.samples)
    return ordered[:max_items]


def build_playbook_conclusion(
    confluence: ConfluenceSearchResponse,
    scan: ArtifactScanResponse,
    *,
    shared_anchors: list[str],
) -> IncidentConclusionResponse:
    page = confluence.top_page
    if page is None:
        return IncidentConclusionResponse(
            status="error",
            errors=["Нет страницы Confluence для playbook."],
        )

    body = confluence.body_plain or page.title
    if len(body) > 12000:
        body = body[:12000] + "\n\n… *(текст страницы обрезан)*"

    lines = [
        f"# {page.title}",
        "",
        f"**Источник:** [Confluence]({page.url}) (`pageId={page.page_id}`)",
        "",
        body,
        "",
        "## Подтверждение в логах",
        "",
    ]

    citations = _pick_citation_samples(scan, shared_anchors)
    if not citations:
        lines.append(
            "_В логах не сохранены примеры строк для общих якорей; "
            "опирайтесь на счётчики скана артефактов._"
        )
    else:
        for c in citations:
            note = "" if c.window == "narrow" else " *(вне узкого окна жалобы)*"
            lines.append(
                f"- `{c.file}:{c.line_number}` — якорь **{c.matched}**{note}: "
                f"`{c.text[:240]}`"
            )

    if shared_anchors:
        lines.extend(
            [
                "",
                "**Совпавшие якоря (статья ∩ логи):** "
                + ", ".join(f"`{a}`" for a in shared_anchors[:12]),
            ]
        )

    return IncidentConclusionResponse(
        status="ok",
        conclusion_markdown="\n".join(lines),
        confidence="high",
        confidence_reason="Ответ из готовой статьи Confluence, подтверждённой якорями в логах.",
        supported_by=[
            f"Confluence: {page.title}",
            f"Якорей в логах: {len(shared_anchors)}",
        ],
        not_proven=["Детали вне текста статьи и выбранных цитат не проверялись."],
        recommended_actions=["Следуйте рекомендациям в статье Confluence выше."],
        conclusion_source="confluence",
        confluence_page_id=page.page_id,
        confluence_title=page.title,
        confluence_url=page.url,
    )
