"""R10.5.7 P0-2 动态 SEED_LIMIT 单元测试.

覆盖:
  1. 高相关性 median ≥ 8.0 → seed_limit = 10 (SEED_LIMIT_MAX)
  2. 中等相关 6.0 ≤ median < 8.0 → seed_limit = 5 (SEED_LIMIT_DEFAULT)
  3. 低相关 median < 6.0 → seed_limit = 3 (SEED_LIMIT_MIN)
  4. ranked_papers 缺失 → seed_limit = 5 (向后兼容)
  5. relevance_score 全 0 → 兼容路径, 不过滤阈值
  6. CITATION_THRESHOLD 过滤: rel < 6.0 的 seed 不进 top
  7. 兜底: 阈值过滤后空 → top-3 兜底, 不至于无扩展
"""
from __future__ import annotations

import asyncio
from typing import cast

import pytest

from backend.agents.citation_expander import (
    expand_citations_node,
    SEED_LIMIT_MIN,
    SEED_LIMIT_MAX,
    SEED_LIMIT_DEFAULT,
    CITATION_THRESHOLD,
)
from backend.models.paper import Paper
from backend.models.state import SearchState


def _make_state(*, ranked_papers: list[dict] | None = None, raw_papers: list[Paper] | None = None) -> dict:
    return {
        "original_query": "test",
        "iteration": 1,
        "raw_papers": [p.to_dict() for p in (raw_papers or [])],
        "ranked_papers": ranked_papers or [],
        "expanded_paper_ids": [],
        "total_cost_usd": 0.0,
    }


def _make_ss_paper(paper_id: str, citation_count: int = 50, relevance: float = 0.0) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        abstract="x" * 100,
        citation_count=citation_count,
        relevance_score=relevance,
        source="semantic_scholar",
    )


def _make_ranked_dict(paper_id: str, relevance: float) -> dict:
    return {
        "paper_id": paper_id,
        "relevance_score": relevance,
        "citation_count": 50,
        "title": f"Ranked {paper_id}",
    }


@pytest.fixture
def mock_ss_api(monkeypatch):
    """Mock SS API 返空, 我们只关心 seed 选择逻辑."""
    from backend.api import semantic_scholar
    async def fake_refs(pid, limit=20):
        return []
    async def fake_cites(pid, limit=10):
        return []
    monkeypatch.setattr(semantic_scholar, "get_references", fake_refs)
    monkeypatch.setattr(semantic_scholar, "get_citations", fake_cites)


# ===== 动态 SEED_LIMIT =====

def test_high_relevance_median_uses_max_seed_limit(monkeypatch, mock_ss_api):
    """median ≥ 8.0 → seed_limit = 10 (SEED_LIMIT_MAX)."""
    # 10 篇 raw SS (高相关, 全过阈值) + 5 篇 ranked median=9.0
    raw = [_make_ss_paper(f"ss_{i}", citation_count=100 - i, relevance=9.0) for i in range(10)]
    ranked = [_make_ranked_dict(f"ss_{i}", relevance=9.0) for i in range(5)]

    async def _run():
        return await expand_citations_node(_make_state(raw_papers=raw, ranked_papers=ranked))

    result = asyncio.run(_run())
    # median=9.0 ≥ 8.0 → seed_limit=10 → candidates 拿 top 10 → 全过阈值 → 10 个
    assert len(result["expanded_paper_ids"]) == 10, f"高相关应全 10 个扩展, got {len(result['expanded_paper_ids'])}"


def test_medium_relevance_uses_default_seed_limit(monkeypatch, mock_ss_api):
    """6.0 ≤ median < 8.0 → seed_limit = 5."""
    raw = [_make_ss_paper(f"ss_{i}", citation_count=100 - i, relevance=7.0) for i in range(10)]
    ranked = [_make_ranked_dict(f"ss_{i}", relevance=7.0) for i in range(5)]

    async def _run():
        return await expand_citations_node(_make_state(raw_papers=raw, ranked_papers=ranked))

    result = asyncio.run(_run())
    # 5 个 ranked seed 全过阈值, 5 进 expanded
    assert len(result["expanded_paper_ids"]) == 5


def test_low_relevance_uses_min_seed_limit(monkeypatch, mock_ss_api):
    """median < 6.0 → seed_limit = 3."""
    raw = [_make_ss_paper(f"ss_{i}", citation_count=100 - i, relevance=4.0) for i in range(10)]
    ranked = [_make_ranked_dict(f"ss_{i}", relevance=4.0) for i in range(5)]

    async def _run():
        return await expand_citations_node(_make_state(raw_papers=raw, ranked_papers=ranked))

    result = asyncio.run(_run())
    # 全部 raw relevance=4 < CITATION_THRESHOLD=6, 过滤后空 → 兜底 top-3
    assert len(result["expanded_paper_ids"]) == 3, "低相关应触发兜底 top-3"


def test_no_ranked_uses_default_seed_limit(monkeypatch, mock_ss_api):
    """ranked_papers 缺失 → 向后兼容 seed_limit = 5."""
    raw = [_make_ss_paper(f"ss_{i}", citation_count=100 - i) for i in range(5)]

    async def _run():
        return await expand_citations_node(_make_state(raw_papers=raw, ranked_papers=None))

    result = asyncio.run(_run())
    # 兼容路径, 5 个 raw 全进
    assert len(result["expanded_paper_ids"]) == 5


def test_relevance_zero_uses_compat_path(monkeypatch, mock_ss_api):
    """relevance_score 全 0 (未走 ranker) → 兼容路径, 5 个全过."""
    raw = [_make_ss_paper(f"ss_{i}", citation_count=100 - i, relevance=0.0) for i in range(5)]

    async def _run():
        return await expand_citations_node(_make_state(raw_papers=raw, ranked_papers=[]))

    result = asyncio.run(_run())
    # 全 0 → has_real_relevance=False → 兼容路径, 不过滤
    assert len(result["expanded_paper_ids"]) == 5


def test_threshold_filters_low_relevance_seeds(monkeypatch, mock_ss_api):
    """CITATION_THRESHOLD 过滤: 部分 seed 低于 6.0 应被剔除."""
    # 5 个 raw, relevance 分布: 9, 9, 7, 3, 3 → median=7
    rels = [9.0, 9.0, 7.0, 3.0, 3.0]
    raw = [_make_ss_paper(f"ss_{i}", citation_count=100 - i, relevance=rels[i]) for i in range(5)]
    # ranked 用同样的 5 个, median=7 → seed_limit=5
    ranked = [_make_ranked_dict(f"ss_{i}", relevance=rels[i]) for i in range(5)]

    async def _run():
        return await expand_citations_node(_make_state(raw_papers=raw, ranked_papers=ranked))

    result = asyncio.run(_run())
    # 2 个 rel=3 < 6 过滤, 剩 3 个; 但 3 >= SEED_LIMIT_MIN=3 兜底阈值,
    # 应该 3 个进 expanded
    assert len(result["expanded_paper_ids"]) == 3, f"应过滤掉 2 个低相关, 剩 3 个, got {len(result['expanded_paper_ids'])}"


def test_constants_exposed():
    """常量正确暴露供外部引用."""
    assert SEED_LIMIT_MIN == 3
    assert SEED_LIMIT_MAX == 10
    assert SEED_LIMIT_DEFAULT == 5
    assert CITATION_THRESHOLD == 6.0
