from __future__ import annotations

import os
from typing import Any

import httpx

from incident_intent.llm_json import LLMError, extract_json_object

DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
DEFAULT_TIMEOUT_SEC = float(os.getenv("OLLAMA_TIMEOUT_SEC", "1200"))
DEFAULT_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))

OllamaError = LLMError


def chat_options(*, temperature: float = 0.1, num_ctx: int | None = None) -> dict[str, Any]:
    return {
        "temperature": temperature,
        "num_ctx": num_ctx if num_ctx is not None else DEFAULT_NUM_CTX,
    }


async def chat_json(
    system: str,
    user: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout_sec: float | None = None,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    model_name = model or DEFAULT_MODEL
    timeout = timeout_sec if timeout_sec is not None else DEFAULT_TIMEOUT_SEC
    payload = {
        "model": model_name,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": chat_options(num_ctx=num_ctx),
    }
    url = f"{base}/api/chat"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = (exc.response.text or "").strip()[:800]
            hint = (
                f" Ollama: {detail}" if detail else ""
            ) or (
                " Проверьте, что модель скачана (ollama-init) и хватает RAM Docker "
                f"(модель {model_name!r}, num_ctx={chat_options(num_ctx=num_ctx)['num_ctx']})."
            )
            raise LLMError(
                f"Ollama ошибка HTTP {exc.response.status_code} ({base}): {exc}.{hint}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Ollama недоступна ({base}): {exc}. "
                "Для Docker задайте OLLAMA_BASE_URL на имя сервиса из docker-compose "
                "(например http://ollama:11434 или http://tsrag-ollama:11434)."
            ) from exc
    data = response.json()
    message = data.get("message") or {}
    content = message.get("content") or ""
    return extract_json_object(content)
