"""Тесты маршрутизации LLM и разбора ответов HF."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from incident_intent import hf_client, llm_client
from incident_intent.llm_json import LLMError, extract_json_object


def test_extract_json_object_from_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert extract_json_object(raw) == {"a": 1}


def test_resolve_hf_api_style_chat_url() -> None:
    assert (
        hf_client.resolve_hf_api_style("https://router.huggingface.co/v1/chat/completions")
        == "chat"
    )


def test_short_http_detail_strips_html() -> None:
    html = "<!DOCTYPE html><html><title>HF</title></html>"
    assert "HTML" in hf_client._short_http_detail(html)


def test_http_error_message_504_hint() -> None:
    msg = hf_client._http_error_message(status=504, url="https://router.hf.co/x", detail="")
    assert "504" in msg
    assert "ollama" in msg.lower() or "Ollama" in msg


def test_resolve_hf_api_style_models_url() -> None:
    assert (
        hf_client.resolve_hf_api_style(
            "https://api-inference.huggingface.co/models/meta-llama/Llama-3.2-3B-Instruct"
        )
        == "generate"
    )


def test_build_router_chat_payload_matches_hf_shape() -> None:
    payload = hf_client.build_router_chat_payload(
        "sys",
        "user text",
        model="Qwen/Qwen3.5-9B:together",
    )
    assert payload["model"] == "Qwen/Qwen3.5-9B:together"
    assert payload["messages"][-1]["role"] == "user"
    assert "user text" in payload["messages"][-1]["content"]
    assert payload["messages"][0] == {"role": "system", "content": "sys"}
    assert "response_format" not in payload


def test_message_text_from_multimodal_content_parts() -> None:
    msg = {
        "role": "assistant",
        "content": [{"type": "text", "text": '{"ok": true}'}],
    }
    assert hf_client._message_text(msg) == '{"ok": true}'


def test_parse_chat_response_hf_router_shape() -> None:
    data = {
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [],
                    "reasoning": 'Thinking...\n\n```json\n{"incident_date": "2026-04-23"}\n```',
                },
                "finish_reason": "stop",
            }
        ],
    }
    parsed = hf_client._parse_chat_response(data)
    assert parsed.content_empty is True
    assert parsed.has_reasoning is True
    assert parsed.finish_reason == "stop"
    assert extract_json_object(parsed.text)["incident_date"] == "2026-04-23"


def test_truncated_reasoning_without_json_raises() -> None:
    parsed = hf_client._ChatParseResult(
        text="Thinking Process only, no json",
        finish_reason="length",
        content_empty=True,
        has_reasoning=True,
    )
    with pytest.raises(LLMError, match="finish_reason=length"):
        hf_client._check_truncated_reasoning(parsed)


def test_build_router_disables_thinking_by_default() -> None:
    with patch.dict(os.environ, {"HF_ENABLE_THINKING": "false"}, clear=False):
        payload = hf_client.build_router_chat_payload("s", "u", model="Qwen/Qwen3.5-9B:together")
    assert payload["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.asyncio
async def test_hf_chat_json_parses_openai_shape() -> None:
    payload = {"choices": [{"message": {"content": '{"ok": true}'}}]}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=FakeResponse())
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(
            hf_client,
            "_hf_inference_url",
            return_value="https://example.com/v1/chat/completions",
        ),
        patch.object(hf_client, "_hf_token", return_value="hf_test"),
        patch.object(hf_client, "_hf_model", return_value="Qwen/Qwen3.5-9B:together"),
        patch("incident_intent.hf_client.httpx.AsyncClient", return_value=fake_client),
    ):
        result = await hf_client.chat_json("sys", "user")

    assert result == {"ok": True}
    call_kwargs = fake_client.post.call_args.kwargs
    assert "Authorization" in call_kwargs["headers"]
    body = call_kwargs["json"]
    assert body["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_llm_client_routes_to_hf() -> None:
    with (
        patch.object(llm_client, "get_llm_provider", return_value="hf"),
        patch.object(
            hf_client, "chat_json", AsyncMock(return_value={"routed": "hf"})
        ) as mock_hf,
    ):
        out = await llm_client.chat_json("s", "u")
    assert out == {"routed": "hf"}
    mock_hf.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_with_retries_on_504() -> None:
    calls = 0

    class FakeResponse:
        status_code = 504

        @property
        def text(self) -> str:
            return "gateway timeout"

        def raise_for_status(self) -> None:
            req = httpx.Request("POST", "https://example.com")
            res = httpx.Response(504, request=req, text="gateway timeout")
            raise httpx.HTTPStatusError("504", request=req, response=res)

    class OkResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    async def fake_post(*_a: object, **_k: object) -> object:
        nonlocal calls
        calls += 1
        if calls < 2:
            return FakeResponse()
        return OkResponse()

    fake_client = AsyncMock()
    fake_client.post = fake_post

    with (
        patch.object(hf_client, "_hf_max_retries", return_value=2),
        patch.object(hf_client, "_hf_retry_backoff_sec", return_value=0.01),
    ):
        resp = await hf_client._post_with_retries(
            fake_client,
            "https://example.com",
            payload={},
            headers={},
        )
    assert calls == 2
    assert resp.json()["choices"][0]["message"]["content"] == '{"ok": true}'


@pytest.mark.asyncio
async def test_hf_missing_token_raises() -> None:
    with (
        patch.object(hf_client, "_hf_inference_url", return_value="https://example.com/x"),
        patch.object(hf_client, "_hf_token", return_value=""),
        pytest.raises(LLMError, match="HF_TOKEN"),
    ):
        await hf_client.chat_json("a", "b")
