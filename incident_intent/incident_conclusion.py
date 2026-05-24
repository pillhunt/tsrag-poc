"""
Шаг 6: итоговое заключение по логам через LLM на основе фактов шагов 1–5.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from incident_intent.conclusion_models import (
    IncidentConclusionRequest,
    IncidentConclusionResponse,
)
from incident_intent.context_analysis import enrich_conclusion_request
from incident_intent.evidence_bundle import build_evidence_payload
from incident_intent.ollama_client import OllamaError, chat_json

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_CONCLUSION_PROMPT = _PROMPTS_DIR / "incident_conclusion_system.md"


@lru_cache(maxsize=1)
def load_conclusion_prompt() -> str:
    if not _CONCLUSION_PROMPT.is_file():
        raise FileNotFoundError(f"Не найден промпт: {_CONCLUSION_PROMPT}")
    return _CONCLUSION_PROMPT.read_text(encoding="utf-8").strip()


def _normalize_confidence(value: str | None) -> Literal["high", "medium", "low"]:
    v = str(value or "medium").lower().strip()
    if v in ("high", "medium", "low"):
        return v  # type: ignore[return-value]
    return "medium"


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if x and str(x).strip()]


def _response_from_raw(raw: dict[str, Any]) -> IncidentConclusionResponse:
    conclusion = str(raw.get("conclusion_markdown") or "").strip()
    if not conclusion:
        conclusion = "Модель не вернула текст заключения."

    return IncidentConclusionResponse(
        status="ok",
        conclusion_markdown=conclusion,
        confidence=_normalize_confidence(raw.get("confidence")),
        confidence_reason=str(raw.get("confidence_reason") or "").strip(),
        supported_by=_as_str_list(raw.get("supported_by")),
        not_proven=_as_str_list(raw.get("not_proven")),
        recommended_actions=_as_str_list(raw.get("recommended_actions")),
        raw_llm=raw,
    )


async def build_incident_conclusion(
    req: IncidentConclusionRequest,
) -> IncidentConclusionResponse:
    if req.filter_summary.time_window_line_count <= 0:
        return IncidentConclusionResponse(
            status="error",
            errors=[
                "Нет среза логов (шаг 1). Сначала выполните обработку инцидента."
            ],
        )

    req = enrich_conclusion_request(req)
    evidence = build_evidence_payload(req)
    user_message = (
        "Факты разбора инцидента (JSON). Напиши заключение по логам и confidence.\n\n"
        + json.dumps(evidence, ensure_ascii=False, indent=2)
    )

    try:
        raw = await chat_json(load_conclusion_prompt(), user_message)
    except OllamaError as exc:
        return IncidentConclusionResponse(
            status="error",
            errors=[str(exc)],
        )
    except FileNotFoundError as exc:
        return IncidentConclusionResponse(
            status="error",
            errors=[str(exc)],
        )

    return _response_from_raw(raw)
