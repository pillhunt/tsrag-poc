"""Тесты маршрутизации LLM и разбора ответов HF."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

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


def test_resolve_hf_api_style_models_url() -> None:
    assert (
        hf_client.resolve_hf_api_style(
            "https://api-inference.huggingface.co/models/meta-llama/Llama-3.2-3B-Instruct"
        )
        == "generate"
    )


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
        patch.object(hf_client, "HF_INFERENCE_URL", "https://example.com/v1/chat/completions"),
        patch.object(hf_client, "HF_TOKEN", "hf_test"),
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
        patch.object(llm_client, "LLM_PROVIDER", "hf"),
        patch.object(
            hf_client, "chat_json", AsyncMock(return_value={"routed": "hf"})
        ) as mock_hf,
    ):
        out = await llm_client.chat_json("s", "u")
    assert out == {"routed": "hf"}
    mock_hf.assert_awaited_once()


@pytest.mark.asyncio
async def test_hf_missing_token_raises() -> None:
    with (
        patch.object(hf_client, "HF_INFERENCE_URL", "https://example.com/x"),
        patch.object(hf_client, "HF_TOKEN", ""),
        pytest.raises(LLMError, match="HF_TOKEN"),
    ):
        await hf_client.chat_json("a", "b")
