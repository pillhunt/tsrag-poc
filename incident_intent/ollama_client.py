from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
# q4_K_M (~5–6 GiB RAM) — разумный дефолт; q6_K (~10 GiB) нужен запас памяти Docker/хоста.
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
DEFAULT_TIMEOUT_SEC = float(os.getenv("OLLAMA_TIMEOUT_SEC", "1200"))
DEFAULT_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))


def chat_options(*, temperature: float = 0.1, num_ctx: int | None = None) -> dict[str, Any]:
    return {
        "temperature": temperature,
        "num_ctx": num_ctx if num_ctx is not None else DEFAULT_NUM_CTX,
    }


class OllamaError(RuntimeError):
    pass


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise OllamaError("Пустой ответ модели")
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
    raise OllamaError("Не удалось разобрать JSON из ответа модели")


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
            raise OllamaError(f"Ollama ошибка HTTP {exc.response.status_code} ({base}): {exc}.{hint}") from exc
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Ollama недоступна ({base}): {exc}. "
                "Для Docker задайте OLLAMA_BASE_URL на имя сервиса из docker-compose "
                "(например http://ollama:11434 или http://tsrag-ollama:11434)."
            ) from exc
    data = response.json()
    message = data.get("message") or {}
    content = message.get("content") or ""
    return _extract_json_object(content)
