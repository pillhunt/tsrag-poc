"""Разбор JSON из ответов LLM (Ollama, Hugging Face и др.)."""

from __future__ import annotations

import json
import re
from typing import Any


class LLMError(RuntimeError):
    pass


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise LLMError("Пустой ответ модели")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise LLMError("Не удалось разобрать JSON из ответа модели")
