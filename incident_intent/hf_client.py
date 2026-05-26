"""Hugging Face Inference API / OpenAI-совместимый chat completions."""

from __future__ import annotations

import os
from typing import Any

import httpx

from incident_intent.llm_json import LLMError, extract_json_object

HF_INFERENCE_URL = os.getenv("HF_INFERENCE_URL", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
HF_MODEL = os.getenv("HF_MODEL", "").strip()
HF_TIMEOUT_SEC = float(os.getenv("HF_TIMEOUT_SEC", os.getenv("OLLAMA_TIMEOUT_SEC", "1200")))
HF_MAX_NEW_TOKENS = int(os.getenv("HF_MAX_NEW_TOKENS", "4096"))
HF_API_STYLE = os.getenv("HF_API_STYLE", "auto").strip().lower()
HF_TEMPERATURE = float(os.getenv("HF_TEMPERATURE", "0.1"))


def is_hf_configured() -> bool:
    return bool(HF_INFERENCE_URL and HF_TOKEN)


def resolve_hf_api_style(url: str | None = None) -> str:
    explicit = HF_API_STYLE
    if explicit in ("chat", "generate"):
        return explicit
    target = (url or HF_INFERENCE_URL).lower()
    if "chat/completions" in target:
        return "chat"
    if "/models/" in target:
        return "generate"
    return "chat"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {HF_TOKEN}"}


def _build_generate_prompt(system: str, user: str) -> str:
    return (
        f"{system.strip()}\n\n"
        f"---\n\n"
        f"{user.strip()}\n\n"
        "Ответь одним валидным JSON-объектом без пояснений вне JSON."
    )


def _parse_generate_response(data: Any) -> str:
    if isinstance(data, list) and data:
        item = data[0]
        if isinstance(item, dict) and "generated_text" in item:
            return str(item["generated_text"])
    if isinstance(data, dict):
        if "generated_text" in data:
            return str(data["generated_text"])
        if "text" in data:
            return str(data["text"])
    raise LLMError(f"Неожиданный формат ответа HF (generate): {data!r}"[:500])


def _parse_chat_response(data: Any) -> str:
    if not isinstance(data, dict):
        raise LLMError(f"Неожиданный формат ответа HF (chat): {data!r}"[:500])
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and message.get("content"):
            return str(message["content"])
    if data.get("generated_text"):
        return str(data["generated_text"])
    if isinstance(data.get("choices"), list) and data["choices"]:
        text = data["choices"][0].get("text")
        if text:
            return str(text)
    raise LLMError(f"Неожиданный формат ответа HF (chat): {data!r}"[:500])


async def chat_json(
    system: str,
    user: str,
    *,
    inference_url: str | None = None,
    model: str | None = None,
    timeout_sec: float | None = None,
    api_style: str | None = None,
) -> dict[str, Any]:
    url = (inference_url or HF_INFERENCE_URL).strip()
    if not url:
        raise LLMError(
            "Hugging Face не настроен: задайте HF_INFERENCE_URL "
            "(полный URL endpoint, например https://api-inference.huggingface.co/models/… "
            "или …/v1/chat/completions)."
        )
    if not HF_TOKEN:
        raise LLMError("Hugging Face не настроен: задайте HF_TOKEN (read token с huggingface.co).")

    style = api_style or resolve_hf_api_style(url)
    timeout = timeout_sec if timeout_sec is not None else HF_TIMEOUT_SEC
    model_name = (model or HF_MODEL).strip()

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if style == "generate":
                payload: dict[str, Any] = {
                    "inputs": _build_generate_prompt(system, user),
                    "parameters": {
                        "max_new_tokens": HF_MAX_NEW_TOKENS,
                        "temperature": HF_TEMPERATURE,
                        "return_full_text": False,
                    },
                }
                response = await client.post(url, json=payload, headers=_auth_headers())
            else:
                body: dict[str, Any] = {
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": HF_MAX_NEW_TOKENS,
                    "temperature": HF_TEMPERATURE,
                }
                if model_name:
                    body["model"] = model_name
                response = await client.post(url, json=body, headers=_auth_headers())
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = (exc.response.text or "").strip()[:800]
            raise LLMError(
                f"Hugging Face HTTP {exc.response.status_code} ({url}): {exc}."
                + (f" {detail}" if detail else "")
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Hugging Face недоступен ({url}): {exc}.") from exc

    data = response.json()
    content = _parse_generate_response(data) if style == "generate" else _parse_chat_response(data)
    return extract_json_object(content)
