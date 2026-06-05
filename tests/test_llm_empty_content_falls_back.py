"""Tests for C4: 200-OK with empty / error body should trigger fallback.

The Anthropic API may return:
  - 200 with content=[]              (truly empty response)
  - 200 with content=[{tool_use,...}] (no text block)
  - 200 with stop_reason="error"

Previously the code returned text="" without setting an error key, so
call_llm's fallback condition `if not text and usage.get("error")` was
False → no fallback → silent degradation downstream.

This test verifies the new behavior:
  1) _call_anthropic_compatible sets `error` key on empty response.
  2) call_llm end-to-end falls back to mock.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import backend.utils.llm_client as llm_client


def _mock_response(content=None, input_tokens=100, output_tokens=0, stop_reason="end_turn"):
    """Build a fake Anthropic Message response with given content."""
    resp = MagicMock()
    resp.content = content if content is not None else []
    resp.usage = MagicMock()
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    resp.stop_reason = stop_reason
    return resp


def test_empty_content_sets_error_key():
    """When resp.content=[], the usage dict must have an 'error' key set."""
    fake_resp = _mock_response(content=[], input_tokens=100, output_tokens=0)

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_resp)

    with patch.object(llm_client, "_get_anthropic_client", return_value=fake_client), \
         patch.object(llm_client, "_call_anthropic_compatible.__wrapped__", create=True) if False else patch.object(llm_client, "get_provider_config", return_value={"enabled": True, "api_key": "k", "base_url": "u"}):
        text, usage = asyncio.run(
            llm_client._call_anthropic_compatible(
                provider="kimi", model="kimi-k2.5", prompt="hi",
                system="sys", max_tokens=100, json_mode=False,
            )
        )

    # text should be empty
    assert text == "", f"Expected empty text, got {text!r}"
    # usage MUST have an error key so call_llm's fallback triggers
    assert "error" in usage, f"Expected 'error' key in usage, got {usage}"
    assert usage["error"] == "empty_response", f"Expected 'empty_response' error, got {usage['error']!r}"
    # input_tokens must still be recorded (billing already incurred)
    assert usage["input_tokens"] == 100


def test_no_text_block_sets_error_key():
    """When content=[{tool_use,...}] (no text block), the usage must have error key."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    # No 'text' attribute on this block
    del tool_block.text  # ensure no text attribute

    fake_resp = _mock_response(content=[tool_block], input_tokens=50, output_tokens=0)

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_resp)

    with patch.object(llm_client, "_get_anthropic_client", return_value=fake_client), \
         patch.object(llm_client, "get_provider_config", return_value={"enabled": True, "api_key": "k", "base_url": "u"}):
        text, usage = asyncio.run(
            llm_client._call_anthropic_compatible(
                provider="kimi", model="kimi-k2.5", prompt="hi",
                system="sys", max_tokens=100, json_mode=False,
            )
        )

    assert text == ""
    assert "error" in usage, f"Expected 'error' key, got {usage}"
    assert usage["error"] == "no_text_block"


def test_stop_reason_error_sets_error_key():
    """When stop_reason='error', usage should have error key (even if text was set)."""
    text_block = MagicMock()
    text_block.text = "partial"

    fake_resp = _mock_response(
        content=[text_block], input_tokens=80, output_tokens=5,
        stop_reason="error",
    )

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_resp)

    with patch.object(llm_client, "_get_anthropic_client", return_value=fake_client), \
         patch.object(llm_client, "get_provider_config", return_value={"enabled": True, "api_key": "k", "base_url": "u"}):
        text, usage = asyncio.run(
            llm_client._call_anthropic_compatible(
                provider="kimi", model="kimi-k2.5", prompt="hi",
                system="sys", max_tokens=100, json_mode=False,
            )
        )

    assert "error" in usage
    assert usage["error"] == "stop_reason_error"


def test_call_llm_falls_back_on_empty_content():
    """End-to-end: call_llm should fall back to mock when real returns empty content."""
    fake_resp = _mock_response(content=[], input_tokens=100, output_tokens=0)

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_resp)

    mock_text = '{"sub_queries": ["a", "b"]}'
    mock_usage = {"model": "mock", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0}

    with patch.object(llm_client, "_get_anthropic_client", return_value=fake_client), \
         patch.object(llm_client, "get_provider_config", return_value={"enabled": True, "api_key": "k", "base_url": "u"}), \
         patch.object(llm_client, "_call_mock",
                      new=AsyncMock(return_value=(mock_text, mock_usage))) as mock_call, \
         patch.object(llm_client, "LLM_MOCK", False), \
         patch.object(llm_client, "LLM_PROVIDER", "kimi"):
        text, usage = asyncio.run(
            llm_client.call_llm("test prompt", task_type="fast_score")
        )

    # Fallback should have triggered
    assert mock_call.called, "Mock fallback was not triggered despite empty content"
    assert text == mock_text
    assert usage.get("fallback_to_mock") is True
