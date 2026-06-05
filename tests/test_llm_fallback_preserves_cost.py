"""Tests for C2: LLM fallback silently loses real-call cost.

When the real LLM call fails (returns empty text with error), the code falls
back to the mock. The mock usage has cost_usd=0, but the real call may have
already incurred billing (input tokens are billed even on error). The
fallback path MUST preserve the real-call cost in the returned usage dict.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

import backend.utils.llm_client as llm_client


def test_fallback_preserves_real_call_cost():
    """Mock _call_anthropic_compatible to fail with $0.15 real cost.
    Mock _call_mock to return $0.0 mock cost.
    Assert the returned usage has cost_usd >= 0.15 (the real cost, not 0).
    """
    real_text = ""
    real_usage = {
        "model": "kimi-k2.5",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cost_usd": 0.15,
        "error": "5xx",
    }
    mock_text = '{"a":1}'
    mock_usage = {
        "model": "mock",
        "input_tokens": 10,
        "output_tokens": 10,
        "cost_usd": 0.0,
    }

    with patch.object(llm_client, "_call_anthropic_compatible",
                      new=AsyncMock(return_value=(real_text, real_usage))), \
         patch.object(llm_client, "_call_mock",
                      new=AsyncMock(return_value=(mock_text, mock_usage))), \
         patch.object(llm_client, "LLM_MOCK", False), \
         patch.object(llm_client, "LLM_PROVIDER", "kimi"):
        text, usage = asyncio.run(llm_client.call_llm("hello", task_type="fast_score"))

    # Real-call cost must be preserved in returned usage
    assert usage.get("cost_usd", 0.0) >= 0.15, (
        f"Real-call cost was lost in fallback. usage={usage}"
    )

    # The model should indicate fallback
    assert "fallback" in str(usage.get("model", "")).lower() or usage.get("fallback_to_mock") is True, (
        f"Fallback not marked in model field. usage={usage}"
    )

    # Tokens should add up (real + mock)
    assert usage.get("input_tokens", 0) >= 1_000_000
    assert usage.get("output_tokens", 0) >= 10

    # Mock text is the one returned
    assert text == mock_text


def test_fallback_no_cost_real_call_still_succeeds():
    """If real call had 0 cost and 0 tokens, mock fallback still works."""
    real_text = ""
    real_usage = {
        "model": "kimi-k2.5",
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "error": "no client",
    }
    mock_text = '{"a":1}'
    mock_usage = {
        "model": "mock",
        "input_tokens": 5,
        "output_tokens": 3,
        "cost_usd": 0.0,
    }

    with patch.object(llm_client, "_call_anthropic_compatible",
                      new=AsyncMock(return_value=(real_text, real_usage))), \
         patch.object(llm_client, "_call_mock",
                      new=AsyncMock(return_value=(mock_text, mock_usage))), \
         patch.object(llm_client, "LLM_MOCK", False), \
         patch.object(llm_client, "LLM_PROVIDER", "kimi"):
        text, usage = asyncio.run(llm_client.call_llm("hello", task_type="fast_score"))

    assert text == mock_text
    assert usage.get("fallback_to_mock") is True
    # cost_usd should be >= 0 (real 0.0 + mock 0.0)
    assert usage.get("cost_usd", -1) >= 0.0


def test_no_fallback_when_real_succeeds():
    """If real call returns text successfully, no fallback happens."""
    real_text = "ok"
    real_usage = {
        "model": "kimi-k2.5",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": 0.001,
    }

    with patch.object(llm_client, "_call_anthropic_compatible",
                      new=AsyncMock(return_value=(real_text, real_usage))), \
         patch.object(llm_client, "_call_mock",
                      new=AsyncMock()) as mock_call, \
         patch.object(llm_client, "LLM_MOCK", False), \
         patch.object(llm_client, "LLM_PROVIDER", "kimi"):
        text, usage = asyncio.run(llm_client.call_llm("hello", task_type="fast_score"))

    assert text == "ok"
    assert usage.get("cost_usd") == 0.001
    assert usage.get("fallback_to_mock") is not True
    mock_call.assert_not_called()
