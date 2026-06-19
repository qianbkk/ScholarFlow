"""R10.5.46 (P1 LangGraph safety net) 测试: empty_result_streak 防死循环.

覆盖:
  1. search_node 入口调 prune_state (R10.5.46 第一次 pass 也有保护)
  2. 连续 0 结果: empty_result_streak +1
  3. 有结果: empty_result_streak = 0 (reset)
  4. router.should_refine: streak >= 2 + papers < 5 → 强制 synthesize
  5. router.should_refine: streak < 2 → 仍走 refine (正常路径不受影响)
  6. synthesis_agent: streak >= 2 时给友好提示 (建议修改查询措辞)
  7. synthesis_agent: streak < 2 时维持原文案 (向后兼容)
  8. make_initial_state 初始化 streak = 0
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ===== 1. search_node 入口调 prune_state =====

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_search_node_entry_calls_prune_state(monkeypatch):
    """[R10.5.46] search_node 入口必须调 prune_state, 第一次 pass 也有 state cap.

    旧实现 (R10.5.22) 只在 query_refine_node 调, iter 1 (没经过 refine) 没保护.
    R10.5.46 修复: search_node 入口也调一次, 防长 query 用户在第一次 pass 撞
    state 膨胀.

    R10.5.50 修复: 加 monkeypatch fixture, 避免直接赋值污染 state.
    """
    from backend.agents import search_agent

    # 构造一个 raw_papers 已经膨胀的 state (模拟前一次 session 残留)
    inflated_state = {
        "original_query": "test",
        "sub_queries": ["test"],
        "raw_papers": [{"relevance_score": float(i % 10)} for i in range(200)],
        "expanded_papers": [{"relevance_score": float(i % 10)} for i in range(150)],
        "ranked_papers": [{"relevance_score": float(i % 10)} for i in range(100)],
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "searching",
        "error": None,
        "provider": None,
        "request_id": None,
        "top5_summary_cache": None,
        "constraints": None,
        "empty_result_streak": 0,
    }

    # 用 mock 替换 SS/OA 等外部 API, 返空结果, 走完 search_node
    class _EmptyPaper:
        paper_id = "x"
        title = "t"
        year = 2024
        authors = []
        abstract = "abstract " * 20  # > 80 chars
        venue = ""
        url = ""
        doi = None
        citation_count = 0
        references = []
        is_fallback = False

        def to_dict(self):
            return {"paper_id": self.paper_id, "title": self.title, "abstract": self.abstract}

    from backend.models.paper import Paper
    from backend.api import semantic_scholar, openalex, arxiv, crossref, pubmed

    async def _empty(*args, **kwargs):
        return []

    # Patch 所有 5 个源的 search_papers 返空
    for mod in [semantic_scholar, openalex, arxiv, crossref, pubmed]:
        if hasattr(mod, "search_papers"):
            monkeypatch.setattr(mod, "search_papers", _empty)

    try:
        result = await search_agent.search_node(inflated_state)
    finally:
        # 还原 — 实际上 test 结束就清理, 这里不严格需要
        pass

    # 验证: state 被 prune (cap 之后 raw <= 50, ranked <= 30)
    # 重要: 第一次 raw_papers=200 → 必须被 cap 到 50
    # 注意: search_node 也 dedup + filter, 实际 raw 数量可能 < 50.
    # 这里主要验证 raw/expanded/ranked 都不超过 cap
    assert len(result.get("raw_papers", [])) <= 50, (
        f"raw_papers should be capped to 50, got {len(result.get('raw_papers', []))}"
    )
    assert len(result.get("ranked_papers", [])) <= 30, (
        f"ranked_papers should be capped to 30, got {len(result.get('ranked_papers', []))}"
    )


# ===== 2. 连续 0 结果: streak +1 =====

@pytest.mark.asyncio
async def test_empty_results_increment_streak(monkeypatch):
    """[R10.5.46] 5 个源都返 0 → unique=0 → empty_result_streak +1.

    R10.5.50 修复: 加 monkeypatch fixture, 避免状态污染.
    """
    from backend.agents import search_agent
    from backend.api import semantic_scholar, openalex, arxiv, crossref, pubmed

    async def _empty(*args, **kwargs):
        return []

    for mod in [semantic_scholar, openalex, arxiv, crossref, pubmed]:
        if hasattr(mod, "search_papers"):
            monkeypatch.setattr(mod, "search_papers", _empty)

    state = {
        "original_query": "test",
        "sub_queries": ["test"],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "searching",
        "error": None,
        "provider": None,
        "request_id": None,
        "top5_summary_cache": None,
        "constraints": None,
        "empty_result_streak": 0,  # 初始 0
    }

    result = await search_agent.search_node(state)
    # unique=0 → streak 1
    assert result["empty_result_streak"] == 1, (
        f"Empty result should increment streak, got {result['empty_result_streak']}"
    )


@pytest.mark.asyncio
async def test_consecutive_empty_results_increment_streak(monkeypatch):
    """[R10.5.46] 连续 2 次 empty_result → streak=2 → router 强制收口.

    R10.5.50 修复: 加 monkeypatch fixture, 避免状态污染.
    """
    from backend.agents import search_agent
    from backend.api import semantic_scholar, openalex, arxiv, crossref, pubmed

    async def _empty(*args, **kwargs):
        return []

    for mod in [semantic_scholar, openalex, arxiv, crossref, pubmed]:
        if hasattr(mod, "search_papers"):
            monkeypatch.setattr(mod, "search_papers", _empty)

    # 第二次进入 search_node 时, streak 已经是 1
    state = {
        "original_query": "test",
        "sub_queries": ["test"],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "iteration": 1,  # iter 2
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "searching",
        "error": None,
        "provider": None,
        "request_id": None,
        "top5_summary_cache": None,
        "constraints": None,
        "empty_result_streak": 1,  # 上次是 0 结果
    }

    result = await search_agent.search_node(state)
    assert result["empty_result_streak"] == 2, (
        f"Consecutive empty results should accumulate streak, got {result['empty_result_streak']}"
    )


# ===== 3. 有结果: streak = 0 (reset) =====

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_non_empty_results_reset_streak(monkeypatch):
    """[R10.5.46] 有结果时 streak 重置为 0 (防止误判).

    R10.5.50 修复: 加 monkeypatch fixture, 避免直接赋值污染模块状态.
    之前直接 mod.search_papers = _one_paper 跨测试残留, 导致 CI 偶发
    'coroutine was never awaited' warning (其他测试拿到我们的 mock,
    把它当 coroutine 加进 gather 但没 await).
    """
    from backend.agents import search_agent
    from backend.api import semantic_scholar, openalex, arxiv, crossref, pubmed
    from backend.models.paper import Paper

    async def _empty(*args, **kwargs):
        return []

    # Abstract 必须 > 80 字符 (search_agent 过滤条件是 len > 80 严格大于).
    # 用 200+ 字符的 abstract 避免边界 case.
    async def _one_paper(*args, **kwargs):
        return [
            Paper(
                paper_id="p1",
                title="Test Paper",
                year=2024,
                authors=["Alice"],
                abstract=(
                    "This is a real abstract that is deliberately longer than 80 characters "
                    "to pass the search_agent filter (len > 80 strictly). The filter "
                    "strips papers with short abstracts to reduce LLM noise."
                ),
                venue="Nature",
                url="",
                doi=None,
                citation_count=10,
            )
        ]

    # Patch 所有 5 个源, ss 返 1 paper, 其他 4 返 0.
    # (之前 test_consecutive_empty_results_increment_streak 把 5 个都 patch 成 _empty,
    # 这里 ss 覆盖成 _one_paper, 其他 4 保持 _empty.)
    # R10.5.50 修复: 用 monkeypatch 代替直接赋值, 防止跨测试 state 残留.
    monkeypatch.setattr(semantic_scholar, "search_papers", _one_paper)
    for mod in [openalex, arxiv, crossref, pubmed]:
        if hasattr(mod, "search_papers"):
            monkeypatch.setattr(mod, "search_papers", _empty)

    state = {
        "original_query": "test",
        "sub_queries": ["test"],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "iteration": 2,  # iter 3
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "searching",
        "error": None,
        "provider": None,
        "request_id": None,
        "top5_summary_cache": None,
        "constraints": None,
        "empty_result_streak": 2,  # 之前累积到 2
    }

    result = await search_agent.search_node(state)
    # 至少有 1 paper (来自 ss), streak 应重置为 0
    assert len(result.get("raw_papers", [])) >= 1, (
        f"Expected ≥1 paper from semantic_scholar mock, got {len(result.get('raw_papers', []))}"
    )
    assert result["empty_result_streak"] == 0, (
        f"Non-empty result should reset streak to 0, got {result['empty_result_streak']}"
    )


# ===== 4. router: streak >= 2 + papers < 5 → synthesize =====

def test_router_streak_geq_2_forces_synthesize():
    """[R10.5.46] router.should_refine: streak >= 2 + papers < 5 → 强制 synthesize."""
    from backend.workflow.router import should_refine

    state = {
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "ranked_papers": [],  # < 5 papers
        "empty_result_streak": 2,  # 连续 2 次 0 结果
    }
    result = should_refine(state)
    assert result == "synthesize", (
        f"streak >= 2 + papers < 5 should force synthesize, got {result!r}"
    )


def test_router_streak_geq_3_forces_synthesize():
    """[R10.5.46] streak = 3 同样强制 synthesize (防 streak 累积超界)."""
    from backend.workflow.router import should_refine

    state = {
        "iteration": 0,
        "max_iterations": 5,  # 还有余量
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "ranked_papers": [{"relevance_score": 0}],  # 1 paper (不 > 5)
        "empty_result_streak": 3,
    }
    result = should_refine(state)
    assert result == "synthesize"


# ===== 5. router: streak < 2 → 仍走 refine (正常路径不受影响) =====

def test_router_streak_0_still_refines_when_few_papers():
    """[R10.5.46] streak=0 + papers < 5 → 仍走 refine (向后兼容, 第 1 次空结果不该直接收)."""
    from backend.workflow.router import should_refine

    state = {
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "ranked_papers": [],  # < 5
        "empty_result_streak": 0,  # streak 还低
    }
    result = should_refine(state)
    assert result == "refine", (
        f"streak=0 + papers<5 should still refine, got {result!r}"
    )


def test_router_streak_1_still_refines_when_few_papers():
    """[R10.5.46] streak=1 (一次 0 结果) → 仍走 refine, 给 LLM 一次改写机会."""
    from backend.workflow.router import should_refine

    state = {
        "iteration": 1,
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "ranked_papers": [],
        "empty_result_streak": 1,
    }
    result = should_refine(state)
    assert result == "refine"


# ===== 8. make_initial_state 初始化 streak = 0 =====

def test_initial_state_has_streak_zero():
    """[R10.5.46] make_initial_state 必须初始化 empty_result_streak=0.

    否则 TypedDict 声明了字段, 但 state 初始化时缺, LangGraph Checkpoint
    反序列化时报 KeyError (R11+ checkpoint 续传前提).
    """
    from backend.api.routes.models import make_initial_state

    state = make_initial_state(
        safe_query="test",
        max_iterations=3,
        budget=2.0,
        provider="kimi",
    )
    assert "empty_result_streak" in state
    assert state["empty_result_streak"] == 0


# ===== 6+7. synthesis_agent: streak >= 2 给友好提示 =====

@pytest.mark.asyncio
async def test_synthesis_streak_2_friendly_message():
    """[R10.5.46] synthesis_node: streak >= 2 时给用户友好提示, 建议修改查询措辞."""
    from backend.agents import synthesis_agent

    # 喂 streak=2, ranked=[]
    state = {
        "original_query": "xyzzy冷门查询",
        "sub_queries": ["xyzzy冷门查询"],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],  # 空
        "iteration": 2,
        "max_iterations": 3,
        "total_cost_usd": 0.05,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "synthesizing",
        "error": None,
        "provider": "kimi",
        "request_id": "test-rid",
        "top5_summary_cache": None,
        "constraints": None,
        "empty_result_streak": 2,
    }
    result = await synthesis_agent.synthesize_node(state)
    report = result.get("report", "")
    assert "检索结果不足" in report, (
        f"Friendly message should mention 检索结果不足, got: {report[:200]}"
    )
    assert "建议" in report
    assert "查询" in report


@pytest.mark.asyncio
async def test_synthesis_streak_0_legacy_message():
    """[R10.5.46] synthesis_node: streak < 2 维持旧文案 '未检索到相关论文' (向后兼容)."""
    from backend.agents import synthesis_agent

    state = {
        "original_query": "test",
        "sub_queries": ["test"],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "synthesizing",
        "error": None,
        "provider": "kimi",
        "request_id": "test-rid",
        "top5_summary_cache": None,
        "constraints": None,
        "empty_result_streak": 0,  # 第一次空, streak 低
    }
    result = await synthesis_agent.synthesize_node(state)
    report = result.get("report", "")
    assert report == "未检索到相关论文。", (
        f"streak=0 should keep legacy message, got: {report[:200]}"
    )
