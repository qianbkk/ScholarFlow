"""Tests for query_decomposer — R10.5.59b: LLM 模式禁止离线兜底.

历史:
  - R10.5.0 X-9 报告: 8 节点中 query_decomposer 0 单测
  - 早期 _fallback_decompose 在 LLM 失败时返回基于关键词的子查询变体
  - R10.5.59b: 用户明确禁止 LLM 模式 + 本地模式混用, 故 LLM 失败时必须
    raise RuntimeError 让上游 catch 后给用户具体错误 (不再兜底变体)

覆盖:
  1. _fallback_decompose 函数本体仍可用 (仅 local 模式走)
  2. LLM 模式 + LLM 失败 → raise RuntimeError
  3. LLM 模式 + LLM 返非法 JSON → raise RuntimeError
  4. LLM 模式 + LLM 超时 → 抛 TimeoutError (防 hang 整个 pipeline)
  5. local 模式 + LLM 失败 → 仍走 _fallback_decompose 兜底 (兼容离线演示)
  6. LLM 返合法 JSON 时正常解析
"""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.agents.query_decomposer import query_decompose_node, _fallback_decompose


class TestFallbackDecompose:
    """_fallback_decompose 兜底函数 — 仅 local 模式使用 (R10.5.59b)."""

    def test_returns_5_variants(self):
        """兜底返 5 个变体 (base + survey + recent + benchmark + comparison)."""
        result = _fallback_decompose("transformer attention")
        assert len(result) == 5
        assert result[0] == "transformer attention"
        assert any("survey" in q for q in result)
        assert any("recent" in q for q in result)

    def test_handles_empty_query_gracefully(self):
        result = _fallback_decompose("")
        # 至少有一个非空变体, 不抛异常
        assert isinstance(result, list)


def _make_state(query: str, runtime_mode: str = "llm") -> dict:
    """构造 query_decompose_node 输入 state."""
    return {
        "original_query": query,
        "sub_queries": [],
        "total_cost_usd": 0.0,
        "runtime_mode": runtime_mode,
    }


class TestQueryDecomposeNodeLLMModeRaises:
    """R10.5.59b: LLM 模式下 LLM 失败时禁止离线兜底 → 必 raise RuntimeError."""

    def test_raises_when_llm_returns_empty(self, monkeypatch):
        """call_llm 返空 text → 解析失败 → RuntimeError (LLM 模式禁止兜底)."""
        async def _run():
            from backend.agents import query_decomposer as qd

            async def fake_call_llm(*args, **kwargs):
                return "", {"input_tokens": 0, "output_tokens": 0}

            monkeypatch.setattr(qd, "call_llm", fake_call_llm)

            state = _make_state("graph neural network", runtime_mode="llm")
            return await query_decompose_node(state)

        with pytest.raises(RuntimeError, match="LLM 解析失败.*禁止离线兜底"):
            asyncio.run(_run())

    def test_raises_when_llm_returns_invalid_json(self, monkeypatch):
        """call_llm 返非 JSON text → extract_json_object 失败 → RuntimeError."""
        async def _run():
            from backend.agents import query_decomposer as qd

            async def fake_call_llm(*args, **kwargs):
                return "this is not json at all, just rambling text", {
                    "input_tokens": 10, "output_tokens": 5,
                }

            monkeypatch.setattr(qd, "call_llm", fake_call_llm)

            state = _make_state("RAG retrieval", runtime_mode="llm")
            return await query_decompose_node(state)

        with pytest.raises(RuntimeError, match="LLM 解析失败.*禁止离线兜底"):
            asyncio.run(_run())

    def test_raises_timeout_when_llm_hangs(self, monkeypatch):
        """Fix-P: 节点级 30s 超时触发 → 抛 TimeoutError (防 hang 整个 pipeline)."""
        async def _run():
            from backend.agents import query_decomposer as qd
            from backend.agents import _schemas

            async def slow_call_llm(*args, **kwargs):
                await asyncio.sleep(60)
                return "{}", {}

            # 缩 wait_for 超时到 0.05s — patch _schemas 的引用
            original_wait_for = asyncio.wait_for

            async def fast_wait_for(awaitable, timeout=None, **kw):
                return await original_wait_for(awaitable, timeout=0.05)

            monkeypatch.setattr(_schemas.asyncio, "wait_for", fast_wait_for)
            monkeypatch.setattr(qd, "call_llm", slow_call_llm)

            state = _make_state("diffusion model", runtime_mode="llm")
            return await query_decompose_node(state)

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(_run())


class TestQueryDecomposeNodeLocalModeAllowsFallback:
    """local 模式仍允许 _fallback_decompose 兜底 (R10.5.59b 兼容离线演示)."""

    def test_local_mode_falls_back_on_llm_failure(self, monkeypatch):
        """local 模式 + LLM 失败 → _fallback_decompose 兜底."""
        async def _run():
            from backend.agents import query_decomposer as qd

            async def fake_call_llm(*args, **kwargs):
                return "", {"input_tokens": 0, "output_tokens": 0}

            monkeypatch.setattr(qd, "call_llm", fake_call_llm)

            state = _make_state("graph neural network", runtime_mode="local")
            return await query_decompose_node(state)

        result = asyncio.run(_run())
        # 兜底至少 1 个子查询
        assert len(result["sub_queries"]) >= 1
        assert all(isinstance(q, str) for q in result["sub_queries"])


class TestQueryDecomposeNodeParse:
    """LLM 返合法 JSON 时正常解析."""

    def test_parses_sub_queries_from_json(self, monkeypatch):
        """LLM 返合法 JSON → 解析出 sub_queries."""
        async def _run():
            from backend.agents import query_decomposer as qd

            async def fake_call_llm(*args, **kwargs):
                return json.dumps({
                    "sub_queries": [
                        "transformer attention mechanism",
                        "self-attention complexity analysis",
                        "BERT pre-training objectives",
                    ]
                }), {"input_tokens": 100, "output_tokens": 50}

            monkeypatch.setattr(qd, "call_llm", fake_call_llm)

            state = _make_state("transformer", runtime_mode="llm")
            return await query_decompose_node(state)

        result = asyncio.run(_run())
        # 解析出 3 个 sub_queries, 限制 5 不截断
        assert len(result["sub_queries"]) == 3
        assert result["sub_queries"][0] == "transformer attention mechanism"
        assert "BERT pre-training objectives" in result["sub_queries"]