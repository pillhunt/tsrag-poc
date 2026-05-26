"""Единая точка вызова LLM: Ollama (по умолчанию) или Hugging Face."""

from __future__ import annotations

import os
from typing import Any

from incident_intent import hf_client, ollama_client
from incident_intent.llm_json import LLMError

# Обратная совместимость
OllamaError = LLMError


def get_llm_provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").strip().lower() or "ollama"


def llm_config_summary() -> dict[str, Any]:
    provider = get_llm_provider()
    if provider == "hf":
        return {
            "provider": "hf",
            "configured": hf_client.is_hf_configured(),
            "inference_url": hf_client._hf_inference_url() or None,
            "model": hf_client._hf_model() or None,
            "api_style": hf_client.resolve_hf_api_style(),
            "token_set": bool(hf_client._hf_token()),
            "timeout_sec": hf_client._hf_timeout_sec(),
            "max_new_tokens": hf_client._hf_max_new_tokens(),
        }
    return {
        "provider": "ollama",
        "configured": True,
        "base_url": os.getenv("OLLAMA_BASE_URL", ollama_client.DEFAULT_BASE_URL),
        "model": os.getenv("OLLAMA_MODEL", ollama_client.DEFAULT_MODEL),
        "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", str(ollama_client.DEFAULT_NUM_CTX))),
        "timeout_sec": ollama_client.DEFAULT_TIMEOUT_SEC,
    }


async def chat_json(
    system: str,
    user: str,
    *,
    json_hint: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    provider = get_llm_provider()
    if provider == "hf":
        return await hf_client.chat_json(system, user, json_hint=json_hint, **kwargs)
    if provider != "ollama":
        raise LLMError(
            f"Неизвестный LLM_PROVIDER={provider!r}. "
            "Допустимо: ollama, hf."
        )
    return await ollama_client.chat_json(system, user, json_hint=json_hint, **kwargs)
