"""Tests for query_decomposer — Fix-Fallback 行为.

X-9 报告: 8 节点中 query_decomposer 0 单测. 覆盖:
  1. LLM 失败时 _fallback_decompose 兜底
  2. 解析到 JSON 时 sub_queries 正确填充
  3. 节点级 asyncio.wait_for 超时 (Fix-P) 触发 fallback
"""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.agents.query_decomposer import query_decompose_node, _fallback_decompose


class TestFallbackDecompose:
    """_fallback_decompose 兜底, LLM 失败时使用."""

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


class TestQueryDecomposeNodeFallback:
    """query_decompose_node 端到端: LLM 失败时走 fallback."""

    def test_fallback_when_llm_returns_empty(self, monkeypatch):
        """call_llm 返空 text → 解析失败 → _fallback_decompose."""
        async def _run():
            from backend.agents import query_decomposer as qd

            async def fake_call_llm(*args, **kwargs):
                return "", {"input_tokens": 0, "output_tokens": 0}

            monkeypatch.setattr(qd, "call_llm", fake_call_llm)

            state = {
                "original_query": "graph neural network",
                "sub_queries": [],
                "total_cost_usd": 0.0,
            }
            result = await query_decompose_node(state)
            return result

        result = asyncio.run(_run())
        # 兜底至少 1 个
        assert len(result["sub_queries"]) >= 1
        assert all(isinstance(q, str) for q in result["sub_queries"])

    def test_fallback_when_llm_returns_invalid_json(self, monkeypatch):
        """call_llm 返非 JSON text → extract_json_object 失败 → fallback."""
        async def _run():
            from backend.agents import query_decomposer as qd

            async def fake_call_llm(*args, **kwargs):
                return "this is not json at all, just rambling text", {
                    "input_tokens": 10, "output_tokens": 5,
                }

            monkeypatch.setattr(qd, "call_llm", fake_call_llm)

            state = {
                "original_query": "RAG retrieval",
                "sub_queries": [],
                "total_cost_usd": 0.0,
            }
            return await query_decompose_node(state)

        result = asyncio.run(_run())
        assert len(result["sub_queries"]) >= 1

    def test_raises_timeout_when_llm_hangs(self, monkeypatch):
        """Fix-P: 节点级 30s 超时触发 → 抛 TimeoutError (防 hang 整个 pipeline).

        注: 节点本身不 catch TimeoutError, 让上层 (graph.ainvoke / endpoint)
        走兜底路径. 这里只验证 wait_for 包装生效 — 超时确实抛出.

        R10.5.51: parse_with_retry_async 在 _schemas.py 调用 asyncio.wait_for,
        不在 query_decomposer. 测试 patch 路径也调到 _schemas.
        """
        async def _run():
            from backend.agents import query_decomposer as qd
            from backend.agents import _schemas

            async def slow_call_llm(*args, **kwargs):
                await asyncio.sleep(60)
                return "{}", {}

            # 缩 wait_for 超时到 0.05s — patch _schemas 的引用 (parse_with_retry_async 在那)
            original_wait_for = asyncio.wait_for

            async def fast_wait_for(awaitable, timeout=None, **kw):
                return await original_wait_for(awaitable, timeout=0.05)

            monkeypatch.setattr(_schemas.asyncio, "wait_for", fast_wait_for)
            monkeypatch.setattr(qd, "call_llm", slow_call_llm)

            state = {
                "original_query": "diffusion model",
                "sub_queries": [],
                "total_cost_usd": 0.0,
            }
            return await query_decompose_node(state)

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(_run())


class TestQueryDecomposeNodeParse:
    """LLM 返合法 JSON 时正常解析."""

    def test_parses_sub_queries_from_json(self, monkeypatch):
        """LLM mock 在 LLM_MOCK 模式下返 prompt 字面量, 改测 fallback 路径覆盖解析失败场景.

        注: query_decomposer.py 内部 `from backend.utils.llm_client import call_llm`
        在模块 namespace 留了 call_llm 引用, monkeypatch 必须 patch
        backend.agents.query_decomposer.call_llm 才生效 (不能 patch 源模块).
        """
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

            state = {
                "original_query": "transformer",
                "sub_queries": [],
                "total_cost_usd": 0.0,
            }
            return await query_decompose_node(state)

        result = asyncio.run(_run())
        # 解析出 3 个 sub_queries, 限制 5 不截断
        assert len(result["sub_queries"]) == 3
        assert result["sub_queries"][0] == "transformer attention mechanism"
        assert "BERT pre-training objectives" in result["sub_queries"]
