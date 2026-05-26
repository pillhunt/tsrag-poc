"""Разбор JSON из ответов LLM (Ollama, Hugging Face и др.)."""

from __future__ import annotations

import json
import re
from typing import Any

# Ключи таблицы намерений (шаг 0) — выбор лучшего объекта среди нескольких {...} в ответе.
_INTENT_TABLE_KEYS = frozenset(
    {
        "incident_date",
        "symptoms",
        "search_keywords",
        "investigation_goal",
        "clarifying_questions",
        "missing_fields",
    }
)

# Ключи заключения (шаг 11)
_CONCLUSION_KEYS = frozenset(
    {
        "summary",
        "confidence",
        "supported_by",
        "not_proven",
        "recommended_actions",
    }
)


class LLMError(RuntimeError):
    pass


def _in_string_at(text: str, pos: int) -> bool:
    """True, если pos внутри JSON-строки (учёт экранирования)."""
    in_string = False
    escape = False
    for i in range(pos):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
    return in_string


def _balanced_json_substrings(text: str) -> list[str]:
    """Все подстроки вида {...} с корректной вложенностью скобок."""
    found: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        start = text.find("{", i)
        if start < 0:
            break
        if _in_string_at(text, start):
            i = start + 1
            continue
        depth = 0
        in_string = False
        escape = False
        end: int | None = None
        for j in range(start, n):
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end is None:
            break
        found.append(text[start : end + 1])
        i = end + 1
    return found


def _parse_dict_candidate(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _pick_best_dict(candidates: list[dict[str, Any]], hint_keys: frozenset[str] | None) -> dict[str, Any] | None:
    if not candidates:
        return None
    if hint_keys:
        for item in reversed(candidates):
            if hint_keys & item.keys():
                return item
    return candidates[-1]


def extract_json_object(
    text: str,
    *,
    hint_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """
    Извлечь один JSON-объект из ответа модели.
    Поддерживает: чистый JSON, ```json fences, reasoning с JSON внутри, несколько {...}.
    """
    text = text.strip()
    if not text:
        raise LLMError("Пустой ответ модели")

    candidates: list[dict[str, Any]] = []

    whole = _parse_dict_candidate(text)
    if whole is not None:
        candidates.append(whole)

    for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE):
        for sub in _balanced_json_substrings(block):
            parsed = _parse_dict_candidate(sub)
            if parsed is not None:
                candidates.append(parsed)

    for sub in _balanced_json_substrings(text):
        parsed = _parse_dict_candidate(sub)
        if parsed is not None and not any(parsed == c for c in candidates):
            candidates.append(parsed)

    chosen = _pick_best_dict(candidates, hint_keys)
    if chosen is not None:
        return chosen

    preview = re.sub(r"\s+", " ", text[:500]).strip()
    raise LLMError(
        "Не удалось разобрать JSON из ответа модели. "
        "Модель могла вернуть только рассуждения (reasoning) без JSON — "
        "уменьшите HF_MAX_NEW_TOKENS, смените модель или включите Ollama. "
        f"Фрагмент ответа ({len(text)} симв.): {preview!r}"
    )


def extract_intent_table_json(text: str) -> dict[str, Any]:
    return extract_json_object(text, hint_keys=_INTENT_TABLE_KEYS)


def extract_conclusion_json(text: str) -> dict[str, Any]:
    return extract_json_object(text, hint_keys=_CONCLUSION_KEYS)
