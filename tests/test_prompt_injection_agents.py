"""Tests for VULN-001 prompt injection defense in query_decomposer and query_refiner.

C1: Verify that both query_decompose_node and query_refine_node call
wrap_user_input() with the correct tags to isolate untrusted data
(user query + paper metadata) from system instructions.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.models.state import SearchState


def _make_base_state(query: str = "test query") -> SearchState:
    return {
        "original_query": query,
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 2,
        "expanded_paper_ids": [],
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 0.5,
        "model_usage": {},
        "status": "started",
        "error": None,
    }


# ===== query_decompose_node =====

def test_query_decompose_calls_wrap_user_input():
    """query_decompose_node must call wrap_user_input with tag='user_query'."""
    from backend.agents import query_decomposer

    state = _make_base_state("transformer architecture")

    # Patch call_llm to return JSON text
    fake_text = '{"analysis": "x", "sub_queries": ["a", "b"], "key_terms": []}'
    with patch.object(query_decomposer, "call_llm",
                      new=AsyncMock(return_value=(fake_text, {"model": "mock", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0}))) as mock_call, \
         patch.object(query_decomposer, "wrap_user_input",
                      wraps=query_decomposer.wrap_user_input) as mock_wrap, \
         patch.object(query_decomposer, "isolation_system_suffix",
                      wraps=query_decomposer.isolation_system_suffix) as mock_iso:
        asyncio.run(query_decomposer.query_decompose_node(state))

    # wrap_user_input must be called at least once for user_query
    assert mock_wrap.called, "wrap_user_input was not called by query_decompose_node"
    # Check it was called with tag='user_query' and the actual query
    user_query_calls = [
        c for c in mock_wrap.call_args_list
        if c.kwargs.get("tag") == "user_query" or (len(c.args) >= 2 and c.args[1] == "user_query")
    ]
    assert user_query_calls, (
        f"wrap_user_input was not called with tag='user_query'. "
        f"Calls: {mock_wrap.call_args_list}"
    )

    # The first arg should be the user's original query
    first_call = user_query_calls[0]
    actual_text = first_call.args[0] if first_call.args else first_call.kwargs.get("text")
    assert actual_text == "transformer architecture", (
        f"wrap_user_input was called with wrong text: {actual_text!r}"
    )

    # isolation_system_suffix must be called and added to system prompt
    assert mock_iso.called, "isolation_system_suffix was not called by query_decompose_node"
    # Verify it's in the system prompt passed to call_llm
    call_args = mock_call.call_args
    passed_system = call_args.kwargs.get("system", "")
    assert "## 安全规则" in passed_system or "user_query" in passed_system, (
        f"isolation_system_suffix output not found in system prompt: {passed_system!r}"
    )


# ===== query_refine_node =====

def test_query_refine_calls_wrap_user_input():
    """query_refine_node must call wrap_user_input for BOTH user_query and paper_list."""
    from backend.agents import query_refiner

    state = _make_base_state("graph neural networks")
    state["ranked_papers"] = [
        {"title": "Paper A", "year": 2023, "relevance_score": 8.5},
        {"title": "Paper B", "year": 2024, "relevance_score": 7.5},
    ]

    fake_text = '{"gap_analysis": "x", "new_sub_queries": ["q1", "q2"]}'
    with patch.object(query_refiner, "call_llm",
                      new=AsyncMock(return_value=(fake_text, {"model": "mock", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0}))) as mock_call, \
         patch.object(query_refiner, "wrap_user_input",
                      wraps=query_refiner.wrap_user_input) as mock_wrap, \
         patch.object(query_refiner, "isolation_system_suffix",
                      wraps=query_refiner.isolation_system_suffix) as mock_iso:
        asyncio.run(query_refiner.query_refine_node(state))

    # wrap_user_input must be called
    assert mock_wrap.called, "wrap_user_input was not called by query_refine_node"

    # Check for user_query tag
    user_query_calls = [
        c for c in mock_wrap.call_args_list
        if c.kwargs.get("tag") == "user_query" or (len(c.args) >= 2 and c.args[1] == "user_query")
    ]
    assert user_query_calls, (
        f"wrap_user_input not called with tag='user_query'. "
        f"Calls: {mock_wrap.call_args_list}"
    )
    actual_user_query = user_query_calls[0].args[0] if user_query_calls[0].args else user_query_calls[0].kwargs.get("text")
    assert actual_user_query == "graph neural networks"

    # Check for paper_list tag (paper metadata isolation)
    paper_list_calls = [
        c for c in mock_wrap.call_args_list
        if c.kwargs.get("tag") == "paper_list" or (len(c.args) >= 2 and c.args[1] == "paper_list")
    ]
    assert paper_list_calls, (
        f"wrap_user_input not called with tag='paper_list'. "
        f"Calls: {mock_wrap.call_args_list}"
    )

    # isolation_system_suffix must be called
    assert mock_iso.called, "isolation_system_suffix was not called by query_refine_node"
