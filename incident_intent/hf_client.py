"""
Hugging Face Inference API.

Router (как в документации HF):
  POST https://router.huggingface.co/v1/chat/completions
  Authorization: Bearer $HF_TOKEN
  {"model": "Qwen/...", "messages": [{"role": "user", "content": "..."}]}

PoC — только текст (content строкой). Мультимодальный content=[{type,text}, …] не используется.
"""

from __future__ import annotations

import asyncio
import json as json_lib
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from incident_intent.llm_json import LLMError, extract_conclusion_json, extract_intent_table_json

def _hf_inference_url() -> str:
    return os.getenv("HF_INFERENCE_URL", "").strip()


def _hf_token() -> str:
    return os.getenv("HF_TOKEN", "").strip()


def _hf_model() -> str:
    return os.getenv("HF_MODEL", "").strip()


def _hf_timeout_sec() -> float:
    return float(os.getenv("HF_TIMEOUT_SEC", os.getenv("OLLAMA_TIMEOUT_SEC", "1200")))


def _hf_max_new_tokens() -> int:
    return int(os.getenv("HF_MAX_NEW_TOKENS", "4096"))


def _hf_api_style() -> str:
    return os.getenv("HF_API_STYLE", "auto").strip().lower()


def _hf_temperature() -> float:
    return float(os.getenv("HF_TEMPERATURE", "0.1"))


def _hf_json_response_format() -> bool:
    """Доп. поле OpenAI; в примере HF router его нет — по умолчанию выключено."""
    return os.getenv("HF_JSON_RESPONSE_FORMAT", "false").lower() in ("1", "true", "yes")


def _hf_enable_thinking() -> bool:
    """Qwen3.5 на router: thinking уходит в message.reasoning и съедает max_tokens."""
    return os.getenv("HF_ENABLE_THINKING", "false").lower() in ("1", "true", "yes")


def _hf_send_max_tokens() -> bool:
    return os.getenv("HF_SEND_MAX_TOKENS", "true").lower() not in ("0", "false", "no")


def _hf_max_retries() -> int:
    return max(0, int(os.getenv("HF_MAX_RETRIES", "3")))


def _hf_retry_backoff_sec() -> float:
    return float(os.getenv("HF_RETRY_BACKOFF_SEC", "5"))


_RETRYABLE_HTTP_STATUS = frozenset({429, 502, 503, 504})


def is_hf_configured() -> bool:
    return bool(_hf_inference_url() and _hf_token())


def resolve_hf_api_style(url: str | None = None) -> str:
    explicit = _hf_api_style()
    if explicit in ("chat", "generate"):
        return explicit
    target = (url or _hf_inference_url()).lower()
    if "chat/completions" in target:
        return "chat"
    if "/models/" in target:
        return "generate"
    return "chat"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_hf_token()}"}


def _httpx_timeout(total_sec: float) -> httpx.Timeout:
    connect = min(60.0, total_sec)
    return httpx.Timeout(connect=connect, read=total_sec, write=total_sec, pool=connect)


def _short_http_detail(text: str, *, limit: int = 400) -> str:
    text = text.strip()
    if not text:
        return ""
    if re.search(r"<html|<!doctype", text, re.I):
        return "(сервер вернул HTML-страницу вместо JSON — обычно перегрузка или таймаут шлюза HF)"
    return text[:limit]


def _http_error_message(*, status: int, url: str, detail: str) -> str:
    base = f"Hugging Face HTTP {status} ({url})."
    if status == 504:
        return (
            f"{base} Gateway Time-out: шлюз HF не дождался ответа модели "
            f"(часто Qwen/reasoning или перегрузка router). "
            f"Повторите запрос; при повторении уменьшите HF_MAX_NEW_TOKENS, "
            f"выберите instruct-модель без reasoning, Dedicated Endpoint "
            f"или временно LLM_PROVIDER=ollama. {detail}".strip()
        )
    if status == 429:
        return f"{base} Слишком много запросов — подождите и повторите. {detail}".strip()
    return f"{base} {detail}".strip()


async def _post_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> httpx.Response:
    retries = _hf_max_retries()
    last_error: httpx.HTTPStatusError | None = None
    for attempt in range(retries + 1):
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            code = exc.response.status_code
            if code not in _RETRYABLE_HTTP_STATUS or attempt >= retries:
                raise
            await asyncio.sleep(_hf_retry_backoff_sec() * (2**attempt))
    if last_error is not None:
        raise last_error
    raise LLMError("Не удалось выполнить запрос к Hugging Face.")


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


def _content_to_text(content: Any) -> str:
    """content: строка (текст) или список частей [{type: text|image_url, ...}] как в HF router."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                chunks.append(str(part.get("text") or "").strip())
        return "\n".join(c for c in chunks if c)
    return ""


@dataclass(frozen=True)
class _ChatParseResult:
    """Разбор ответа HF router: choices[0].message + finish_reason."""

    text: str
    finish_reason: str | None
    content_empty: bool
    has_reasoning: bool


def _message_text(message: dict[str, Any]) -> str:
    """Как response['choices'][0]['message'] в примере HF: content и/или reasoning."""
    parts: list[str] = []
    content_text = _content_to_text(message.get("content"))
    if content_text:
        parts.append(content_text)
    reasoning = message.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        parts.append(reasoning.strip())
    for key in ("text",):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function")
            if isinstance(fn, dict):
                args = fn.get("arguments")
                if isinstance(args, str) and args.strip():
                    parts.append(args.strip())
    return "\n\n".join(parts)


def _parse_chat_response(data: Any) -> _ChatParseResult:
    """
    Структура HF router (chat.completion):
      choices[0].message.{content, reasoning, tool_calls}
      choices[0].finish_reason  — 'length' = обрезка по max_tokens
    """
    if not isinstance(data, dict):
        raise LLMError(f"Неожиданный формат ответа HF (chat): {data!r}"[:500])

    choices = data.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            finish_reason = choice.get("finish_reason")
            if isinstance(finish_reason, str):
                finish_reason = finish_reason.strip() or None
            else:
                finish_reason = None

            message = choice.get("message")
            if isinstance(message, dict):
                content_raw = message.get("content")
                content_empty = not _content_to_text(content_raw)
                has_reasoning = bool(
                    isinstance(message.get("reasoning"), str)
                    and str(message.get("reasoning")).strip()
                )
                text = _message_text(message)
                if text:
                    return _ChatParseResult(
                        text=text,
                        finish_reason=finish_reason,
                        content_empty=content_empty,
                        has_reasoning=has_reasoning,
                    )
            delta = choice.get("delta")
            if isinstance(delta, dict):
                text = _message_text(delta)
                if text:
                    return _ChatParseResult(
                        text=text,
                        finish_reason=finish_reason,
                        content_empty=not bool(_content_to_text(delta.get("content"))),
                        has_reasoning=bool(delta.get("reasoning")),
                    )
            legacy = choice.get("text")
            if isinstance(legacy, str) and legacy.strip():
                return _ChatParseResult(
                    text=legacy.strip(),
                    finish_reason=finish_reason,
                    content_empty=True,
                    has_reasoning=False,
                )

    if data.get("generated_text"):
        return _ChatParseResult(
            text=str(data["generated_text"]),
            finish_reason=None,
            content_empty=True,
            has_reasoning=False,
        )

    raise LLMError(
        "Пустой ответ HF (chat): у модели нет content/reasoning в choices. "
        "Попробуйте другую модель или увеличьте HF_MAX_NEW_TOKENS."
    )


def _apply_extra_body(payload: dict[str, Any]) -> None:
    raw = os.getenv("HF_EXTRA_BODY_JSON", "").strip()
    if raw:
        extra = json_lib.loads(raw)
        if not isinstance(extra, dict):
            raise LLMError("HF_EXTRA_BODY_JSON должен быть JSON-объектом")
        payload.update(extra)
        return
    if not _hf_enable_thinking():
        kwargs = payload.setdefault("chat_template_kwargs", {})
        if isinstance(kwargs, dict):
            kwargs["enable_thinking"] = False


def _check_truncated_reasoning(parsed: _ChatParseResult) -> None:
    if parsed.finish_reason != "length":
        return
    if "{" in parsed.text and "}" in parsed.text:
        return
    raise LLMError(
        "Ответ HF обрезан (finish_reason=length): лимит токенов исчерпан на reasoning, "
        f"JSON не появился (HF_MAX_NEW_TOKENS={_hf_max_new_tokens()}). "
        "Увеличьте HF_MAX_NEW_TOKENS (например 8192), задайте HF_ENABLE_THINKING=false "
        "(по умолчанию) или выберите instruct-модель без thinking."
    )


def _extract_json_from_hf_chat(
    parsed: _ChatParseResult,
    *,
    json_hint: str | None,
) -> dict[str, Any]:
    _check_truncated_reasoning(parsed)
    try:
        if json_hint == "conclusion":
            return extract_conclusion_json(parsed.text)
        return extract_intent_table_json(parsed.text)
    except LLMError as exc:
        if parsed.content_empty and parsed.has_reasoning:
            raise LLMError(
                f"{exc} "
                "HF вернул пустой message.content и длинный message.reasoning — "
                "для Qwen отключите thinking (HF_ENABLE_THINKING=false) и увеличьте "
                "HF_MAX_NEW_TOKENS."
            ) from exc
        raise


def build_router_chat_payload(
    system: str,
    user: str,
    *,
    model: str,
) -> dict[str, Any]:
    """
    Тело запроса в стиле HF router chat/completions (только текст).
    Совпадает с официальным примером: model + messages + Bearer token.
    """
    if not model.strip():
        raise LLMError(
            "Для HF router задайте HF_MODEL, например Qwen/Qwen3.5-9B:together"
        )
    messages: list[dict[str, Any]] = []
    if system.strip():
        messages.append({"role": "system", "content": system.strip()})
    user_text = user.strip()
    if "JSON" not in user_text[-300:].upper():
        user_text = (
            f"{user_text}\n\n"
            "Итог: один JSON-объект по схеме из system (incident_date, symptoms, …). "
            "Без reasoning и без текста вне JSON."
        )
    messages.append({"role": "user", "content": user_text})

    payload: dict[str, Any] = {"model": model.strip(), "messages": messages}
    if _hf_send_max_tokens():
        payload["max_tokens"] = _hf_max_new_tokens()
    if _hf_temperature() >= 0:
        payload["temperature"] = _hf_temperature()
    if _hf_json_response_format():
        payload["response_format"] = {"type": "json_object"}
    _apply_extra_body(payload)
    return payload


async def chat_json(
    system: str,
    user: str,
    *,
    inference_url: str | None = None,
    model: str | None = None,
    timeout_sec: float | None = None,
    api_style: str | None = None,
    json_hint: str | None = None,
) -> dict[str, Any]:
    url = (inference_url or _hf_inference_url()).strip()
    if not url:
        raise LLMError(
            "Hugging Face не настроен: задайте HF_INFERENCE_URL "
            "(полный URL endpoint, например https://api-inference.huggingface.co/models/… "
            "или …/v1/chat/completions)."
        )
    if not _hf_token():
        raise LLMError("Hugging Face не настроен: задайте HF_TOKEN (read token с huggingface.co).")

    style = api_style or resolve_hf_api_style(url)
    timeout = timeout_sec if timeout_sec is not None else _hf_timeout_sec()
    model_name = (model or _hf_model()).strip()

    headers = _auth_headers()
    if style == "generate":
        payload: dict[str, Any] = {
            "inputs": _build_generate_prompt(system, user),
            "parameters": {
                "max_new_tokens": _hf_max_new_tokens(),
                "temperature": _hf_temperature(),
                "return_full_text": False,
            },
        }
    else:
        if not model_name:
            raise LLMError(
                "Для HF router укажите HF_MODEL в env/docker.env "
                '(например "Qwen/Qwen3.5-9B:together").'
            )
        payload = build_router_chat_payload(system, user, model=model_name)

    async with httpx.AsyncClient(timeout=_httpx_timeout(timeout)) as client:
        try:
            response = await _post_with_retries(
                client, url, payload=payload, headers=headers
            )
        except httpx.HTTPStatusError as exc:
            detail = _short_http_detail(exc.response.text or "")
            raise LLMError(
                _http_error_message(
                    status=exc.response.status_code, url=url, detail=detail
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Hugging Face недоступен ({url}): {exc}.") from exc

    data = response.json()
    if style == "generate":
        return extract_intent_table_json(_parse_generate_response(data))
    parsed = _parse_chat_response(data)
    return _extract_json_from_hf_chat(parsed, json_hint=json_hint)
