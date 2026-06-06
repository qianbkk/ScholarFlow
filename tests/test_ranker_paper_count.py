"""ranker 论文数 = 25 (P0) 修复测试。

旧 bug：ranker_agent.py 输出 `papers[:30]`，但 synthesis_agent 与
graph_builder 都按 `[:20]` / `[:25]` 截断。结果 21-30 名论文的
ranker 评分（relevance / authority / consistency / final_score）
永远不会被下游使用 → 暗物质（不可见计算浪费 token）。

新实现：ranker 也截到 25，与 synthesis / graph 对齐。

测试覆盖：
  1) test_rank_caps_to_25: 30 个 paper mock 进去 → ranked_papers 长度 = 25
  2) test_rank_caps_to_25_preserves_top_by_score: top 25 by final_score 被保留
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.models.paper import Paper
from backend.agents import ranker_agent
from backend.agents.ranker_agent import rank_node


# ===== Helpers =====

def _make_paper(pid: str, cites: int = 10) -> Paper:
    return Paper(
        paper_id=pid,
        title=f"Paper {pid}",
        year=2024,
        authors=["Author"],
        citation_count=cites,
        abstract=(
            f"Sufficiently long abstract for {pid} describing novel contributions "
            "to machine learning research that are useful for testing."
        ),
        venue="NeurIPS",
        source="semantic_scholar",
    )


def _build_state(papers: list[Paper], query: str = "transformer") -> dict:
    return {
        "original_query": query,
        "sub_queries": [query],
        "raw_papers": [p.to_dict() for p in papers],
        "expanded_papers": [p.to_dict() for p in papers],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 3,
        "expanded_paper_ids": [],
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 5.0,
        "model_usage": {},
        "status": "ranking",
        "error": None,
    }


# ===== 1) 30 个 paper 进去 → ranked 25 =====

def test_rank_caps_to_25():
    """30 篇 paper → ranked_papers 长度 = 25（不是 30, 不是 20）。"""
    papers = [_make_paper(f"p_{i:02d}", cites=10) for i in range(30)]
    state = _build_state(papers)

    # Mock LLM combined-batch scoring → 返回稳定 5.0/6.0 分数
    async def fake_combined(batch, query, provider=None):
        return ([5.0] * len(batch), [6.0] * len(batch), {
            "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
        })

    async def run():
        with patch.object(ranker_agent, "_score_papers_combined_batch", side_effect=fake_combined):
            return await rank_node(state)

    result = asyncio.run(run())
    ranked = result["ranked_papers"]
    assert len(ranked) == 25, (
        f"30 篇 paper 排名后应剩 25 篇 (与 synthesis/graph 对齐), 实际 {len(ranked)}"
    )


# ===== 2) 25 个 paper 进去 → 25 个出来 =====

def test_rank_returns_25_when_input_equals_25():
    """25 篇 paper 输入 → 25 篇输出 (上界是 25, 不是严格截断)。"""
    papers = [_make_paper(f"p_{i:02d}", cites=10) for i in range(25)]
    state = _build_state(papers)

    async def fake_combined(batch, query, provider=None):
        return ([5.0] * len(batch), [6.0] * len(batch), {
            "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
        })

    async def run():
        with patch.object(ranker_agent, "_score_papers_combined_batch", side_effect=fake_combined):
            return await rank_node(state)

    result = asyncio.run(run())
    assert len(result["ranked_papers"]) == 25


# ===== 3) 排序按 final_score 降序 =====

def test_rank_orders_by_final_score_descending():
    """ranked_papers 应按 final_score 降序排列 (高分在前)。"""
    # 5 篇 citation_count 不同 → 不同 authority_score → 不同 final_score
    papers = [_make_paper(f"p_{i:02d}", cites=(i + 1) * 50) for i in range(5)]
    state = _build_state(papers)

    async def fake_combined(batch, query, provider=None):
        # relevance=5.0, consistency=6.0 → final = 5*0.5 + auth*0.3 + 6*0.2
        # = 2.5 + 0.3*auth + 1.2 = 3.7 + 0.3*auth
        # auth 由 citation_count 决定: 高 cites → 高 auth → 高 final
        return ([5.0] * len(batch), [6.0] * len(batch), {
            "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
        })

    async def run():
        with patch.object(ranker_agent, "_score_papers_combined_batch", side_effect=fake_combined):
            return await rank_node(state)

    result = asyncio.run(run())
    ranked = result["ranked_papers"]
    scores = [p["final_score"] for p in ranked]
    # 验证降序
    assert scores == sorted(scores, reverse=True), (
        f"ranked_papers 应按 final_score 降序, 实际 {scores}"
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
