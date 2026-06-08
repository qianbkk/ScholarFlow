"""Tests for citation_expander.expand_citations_node — Fix 跨迭代去重.

X-9 报告: 8 个核心节点只 3 个有针对性测试, 补 citation_expander.
覆盖跨迭代去重逻辑: 第二轮 iter=1 时跳过已扩展过的 seed paper_id.
"""
from __future__ import annotations

import asyncio
from typing import cast

import pytest

from backend.agents.citation_expander import expand_citations_node
from backend.models.paper import Paper
from backend.models.state import SearchState


def _make_state(*, iteration: int, raw_papers: list[Paper], expanded_ids: list[str] | None = None) -> dict:
    return {
        "original_query": "test query",
        "iteration": iteration,
        "raw_papers": [p.to_dict() for p in raw_papers],
        "expanded_paper_ids": expanded_ids or [],
        "total_cost_usd": 0.0,
    }


def _make_ss_paper(paper_id: str, citation_count: int = 50, title: str = "Test") -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        abstract="x" * 100,
        citation_count=citation_count,
        source="semantic_scholar",
    )


class TestCitationExpanderSkipAlreadyExpanded:
    """跨迭代去重: SEED_LIMIT=5 但 expanded_ids 已含 N 个 → 跳过."""

    def test_iter1_first_expansion_processes_all_seeds(self, monkeypatch):
        """iter=1, expanded_paper_ids 空 → 处理所有 5 个 seeds."""
        async def _run():
            # mock 5 篇高引 SS 论文
            raw = [_make_ss_paper(f"ss_{i}", citation_count=100 - i) for i in range(5)]
            state = _make_state(iteration=1, raw_papers=raw, expanded_ids=[])

            # mock semantic_scholar.get_references / get_citations 返空 list
            from backend.api import semantic_scholar
            async def fake_refs(pid, limit=20):
                return []
            async def fake_cites(pid, limit=10):
                return []
            monkeypatch.setattr(semantic_scholar, "get_references", fake_refs)
            monkeypatch.setattr(semantic_scholar, "get_citations", fake_cites)

            result = await expand_citations_node(state)
            return result

        result = asyncio.run(_run())
        # 5 个 seeds 全部应进 expanded_paper_ids
        assert len(result["expanded_paper_ids"]) == 5

    def test_iter2_skips_already_expanded_seeds(self, monkeypatch):
        """iter=2, expanded_paper_ids 已含 5 个 → 跳过, 不重复扩展."""
        async def _run():
            raw = [_make_ss_paper(f"ss_{i}", citation_count=100 - i) for i in range(5)]
            # 全部 5 个已扩展
            state = _make_state(
                iteration=2,
                raw_papers=raw,
                expanded_ids=[f"ss_{i}" for i in range(5)],
            )

            from backend.api import semantic_scholar
            # 如果被错误地调用, 这会暴露 (mock 抛异常)
            call_count = {"n": 0}
            async def fake_refs(pid, limit=20):
                call_count["n"] += 1
                return []
            async def fake_cites(pid, limit=10):
                call_count["n"] += 1
                return []
            monkeypatch.setattr(semantic_scholar, "get_references", fake_refs)
            monkeypatch.setattr(semantic_scholar, "get_citations", fake_cites)

            result = await expand_citations_node(state)
            return result, call_count["n"]

        result, call_count = asyncio.run(_run())
        # 全部 seeds 已扩展, 不应再调 SS API
        assert call_count == 0, f"iter=2 不应调 SS API 0 次, 实际 {call_count} 次"
        # 返回的 expanded_paper_ids 仍是原 5 个
        assert set(result["expanded_paper_ids"]) == {f"ss_{i}" for i in range(5)}

    def test_no_ss_papers_falls_through_to_raw(self, monkeypatch):
        """raw 全部是 openalex source, expand_citations_node 跳过 SS API."""
        async def _run():
            raw = [
                Paper(
                    paper_id=f"oa_{i}", title=f"OA {i}", abstract="x" * 100,
                    source="openalex",
                )
                for i in range(3)
            ]
            state = _make_state(iteration=1, raw_papers=raw)
            result = await expand_citations_node(state)
            return result

        result = asyncio.run(_run())
        # 无 SS 论文, 走兜底: expanded = raw (all)
        assert len(result["expanded_papers"]) == 3
        assert result["status"] == "ranking"
