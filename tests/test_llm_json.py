"""Разбор JSON из ответов LLM."""

from incident_intent.llm_json import (
    LLMError,
    extract_conclusion_json,
    extract_intent_table_json,
    extract_json_object,
)


def test_extract_from_reasoning_with_trailing_json() -> None:
    text = (
        "Thinking Process:\n\n"
        "Need incident_date...\n\n"
        "```json\n"
        '{"incident_date": "2026-04-23", "symptoms": ["медленно"], '
        '"search_keywords": ["save"], "clarifying_questions": []}\n'
        "```"
    )
    data = extract_intent_table_json(text)
    assert data["incident_date"] == "2026-04-23"


def test_extract_nested_braces_not_greedy_broken() -> None:
    text = (
        'prefix {"incident_date": "2026-04-23", "symptoms": [], '
        '"search_keywords": ["a"], "notes": ["x: {not json}"]}'
    )
    data = extract_intent_table_json(text)
    assert data["incident_date"] == "2026-04-23"
    assert "not json" in data["notes"][0]


def test_extract_conclusion_prefers_conclusion_keys() -> None:
    text = (
        '{"incident_date": "x"} '
        '{"summary": "ok", "confidence": "medium", "supported_by": [], '
        '"not_proven": [], "recommended_actions": []}'
    )
    data = extract_conclusion_json(text)
    assert data["summary"] == "ok"


def test_extract_raises_with_preview() -> None:
    try:
        extract_json_object("only plain text, no braces")
    except LLMError as exc:
        assert "Фрагмент ответа" in str(exc)
    else:
        raise AssertionError("expected LLMError")
