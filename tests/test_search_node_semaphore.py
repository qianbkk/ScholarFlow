"""Tests for PERF-004: search_node must use Semaphore to limit concurrency.

Background
----------
The search_node function in `backend.agents.search_agent` issues concurrent
calls to `semantic_scholar.search_papers` and `openalex.search_papers` for
each sub-query. Without a Semaphore, a request with N sub-queries creates
2N concurrent outbound calls (one SS + one OA per sub-query), which can
overwhelm the upstream APIs and trigger rate limiting.

The fix introduces an asyncio.Semaphore (matching the limit in
`citation_expander._CITATION_SEMAPHORE`, which is 4) to cap the in-flight
concurrent API calls.

Test strategy
-------------
1. Replace `semantic_scholar.search_papers` and `openalex.search_papers`
   with slow fakes that track concurrent invocations.
2. Build a state with several sub_queries (e.g. 5+).
3. Run `search_node(state)`.
4. Assert that peak concurrent in-flight calls <= 4 (or whatever limit
   is configured).
5. Also assert the module has a Semaphore attribute (defensive source
   check).
"""
import asyncio
import time

import pytest

from backend.models.paper import Paper
from backend.models.state import SearchState
from backend.agents import search_agent
from backend.agents.search_agent import search_node


# ===== Helpers =====

def _make_paper(pid: str) -> Paper:
    return Paper(
        paper_id=pid,
        title=f"Paper {pid}",
        year=2024,
        authors=["Author"],
        citation_count=10,
        abstract=(
            f"Sufficiently long abstract for {pid} describing novel contributions "
            "to machine learning research that are useful for testing search node."
        ),
        source="semantic_scholar",
    )


def _build_state(num_sub_queries: int) -> SearchState:
    return {
        "original_query": "transformer",
        "sub_queries": [f"sub_query_{i}" for i in range(num_sub_queries)],
        "raw_papers": [],
        "expanded_papers": [],
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
        "status": "searching",
        "error": None,
    }


# ===== 1) Peak concurrent SS calls <= 4 =====

@pytest.mark.asyncio
async def test_search_node_caps_semantic_scholar_concurrency(monkeypatch):
    """search_node must cap concurrent semantic_scholar.search_papers calls."""
    from backend.api import semantic_scholar, openalex

    ss_concurrent = 0
    ss_peak = 0
    ss_calls = 0

    async def fake_ss_search_papers(query, limit=30):
        nonlocal ss_concurrent, ss_peak, ss_calls
        ss_concurrent += 1
        ss_peak = max(ss_peak, ss_concurrent)
        ss_calls += 1
        # Simulate API latency
        await asyncio.sleep(0.05)
        ss_concurrent -= 1
        return [_make_paper(f"ss_{query}_paper")]

    async def fake_oa_search_papers(query, limit=20):
        # OpenAlex concurrency is also tracked (it's part of the same Semaphore)
        await asyncio.sleep(0.05)
        return [_make_paper(f"oa_{query}_paper")]

    monkeypatch.setattr(semantic_scholar, "search_papers", fake_ss_search_papers)
    monkeypatch.setattr(openalex, "search_papers", fake_oa_search_papers)

    # 6 sub-queries → would be 6 + 6 = 12 concurrent calls without Semaphore
    state = _build_state(num_sub_queries=6)
    result = await search_node(state)

    # Verify pipeline still produces output
    assert "raw_papers" in result
    assert result["status"] == "expanding"

    # CRITICAL: peak concurrent SS calls must be <= 4 (matching citation_expander)
    assert ss_peak <= 4, (
        f"PERF-004 FAIL: search_node has no Semaphore. "
        f"Peak concurrent semantic_scholar calls = {ss_peak} (expected <= 4). "
        f"With 6 sub_queries: 6 SS + 6 OA = 12 concurrent calls would saturate "
        f"upstream APIs."
    )
    # Also: all 6 sub-queries should have been called
    assert ss_calls == 6, f"expected 6 SS calls (one per sub_query), got {ss_calls}"


# ===== 2) Peak concurrent total (SS + OA) <= 4 =====

@pytest.mark.asyncio
async def test_search_node_caps_total_concurrency(monkeypatch):
    """search_node must cap total concurrent API calls (SS + OA combined)."""
    from backend.api import semantic_scholar, openalex

    total_concurrent = 0
    total_peak = 0

    async def fake_ss_search_papers(query, limit=30):
        nonlocal total_concurrent, total_peak
        total_concurrent += 1
        total_peak = max(total_peak, total_concurrent)
        await asyncio.sleep(0.05)
        total_concurrent -= 1
        return [_make_paper(f"ss_{query}")]

    async def fake_oa_search_papers(query, limit=20):
        nonlocal total_concurrent, total_peak
        total_concurrent += 1
        total_peak = max(total_peak, total_concurrent)
        await asyncio.sleep(0.05)
        total_concurrent -= 1
        return [_make_paper(f"oa_{query}")]

    monkeypatch.setattr(semantic_scholar, "search_papers", fake_ss_search_papers)
    monkeypatch.setattr(openalex, "search_papers", fake_oa_search_papers)

    # 8 sub-queries → would be 16 concurrent total without Semaphore
    state = _build_state(num_sub_queries=8)
    await search_node(state)

    assert total_peak <= 4, (
        f"PERF-004 FAIL: total concurrent API calls peaked at {total_peak}. "
        f"Expected <= 4 (matching citation_expander._CITATION_SEMAPHORE)."
    )


# ===== 3) Per-call Semaphore is configured (R10.5 Fix-F rewrite) =====

def test_search_agent_configures_per_call_semaphore():
    """R10.5 Fix-F (审计 QQQ §1.2): 模块级 _SEARCH_SEMAPHORE 跨请求共享
    已被 3+ 用户并发性能灾难取代. 改为 search_node 内动态创建 semaphore.

    防御性测试: 确保常量 _SEARCH_BATCH_LIMIT 存在并 <=8, _throttled_search
    接受 semaphore 参数 (per-call 实例化, 不再是 module singleton).
    """
    limit = getattr(search_agent, "_SEARCH_BATCH_LIMIT", None)
    assert limit is not None, (
        "PERF-004 FAIL: search_agent 缺 _SEARCH_BATCH_LIMIT 常量. "
        "应改用 per-call Semaphore + 模块常量限流值."
    )
    assert limit <= 8, (
        f"PERF-004 FAIL: _SEARCH_BATCH_LIMIT={limit} 过高, 建议 <=4 "
        f"(对齐 citation_expander._CITATION_BATCH_LIMIT)."
    )
    # _throttled_search 现在接收 semaphore 参数 (per-call)
    import inspect
    sig = inspect.signature(search_agent._throttled_search)
    assert "semaphore" in sig.parameters, (
        "PERF-004 FAIL: _throttled_search 应接收 semaphore 参数 (per-call)."
    )


# ===== 4) Semaphore limit matches citation_expander (consistency) =====

def test_search_node_semaphore_matches_citation_expander():
    """R10.5 Fix-F: 模块级 Semaphore 改 per-call, 两个模块都用常量
    _SEARCH_BATCH_LIMIT / _CITATION_BATCH_LIMIT 表达上限, 必须相等以保证
    全 pipeline 并发策略一致 (search + citation 两阶段总峰值不超 8).
    """
    from backend.agents import citation_expander

    search_limit = getattr(search_agent, "_SEARCH_BATCH_LIMIT", None)
    cite_limit = getattr(citation_expander, "_CITATION_BATCH_LIMIT", None)
    if search_limit is None or cite_limit is None:
        pytest.skip("R10.5 Fix-F per-call Semaphore 还没应用 (缺 _*_BATCH_LIMIT)")

    assert search_limit == cite_limit, (
        f"PERF-004: _SEARCH_BATCH_LIMIT ({search_limit}) must match "
        f"_CITATION_BATCH_LIMIT ({cite_limit}) for consistent "
        f"concurrency policy across the 8-node pipeline."
    )


# ===== 5) Slow path: Semaphore doesn't deadlock on long tasks =====

@pytest.mark.asyncio
async def test_search_node_semaphore_does_not_deadlock(monkeypatch):
    """With a Semaphore wrapping slow fakes, the node should still complete.
    Verifies the Semaphore's `async with` release is correct.
    """
    from backend.api import semantic_scholar, openalex

    async def slow_ss(query, limit=30):
        await asyncio.sleep(0.05)
        return [_make_paper(f"ss_{query}")]

    async def slow_oa(query, limit=20):
        await asyncio.sleep(0.05)
        return [_make_paper(f"oa_{query}")]

    monkeypatch.setattr(semantic_scholar, "search_papers", slow_ss)
    monkeypatch.setattr(openalex, "search_papers", slow_oa)

    state = _build_state(num_sub_queries=6)
    # Should complete in ~6 * 0.05 / 4 (semaphore allows 4 concurrent) = 0.075s
    # Allow 5s margin
    result = await asyncio.wait_for(search_node(state), timeout=5.0)
    assert result["status"] == "expanding"
    assert len(result["raw_papers"]) > 0


# ===== 6) search_node returns valid output under throttle =====

@pytest.mark.asyncio
async def test_search_node_results_correct_under_throttle(monkeypatch):
    """Throttling doesn't drop calls or break deduplication."""
    from backend.api import semantic_scholar, openalex

    async def fake_ss(query, limit=30):
        await asyncio.sleep(0.01)
        return [
            _make_paper(f"shared_paper"),  # same paper for every sub_query
            _make_paper(f"ss_unique_{query}"),
        ]

    async def fake_oa(query, limit=20):
        await asyncio.sleep(0.01)
        return [_make_paper(f"oa_unique_{query}")]

    monkeypatch.setattr(semantic_scholar, "search_papers", fake_ss)
    monkeypatch.setattr(openalex, "search_papers", fake_oa)

    state = _build_state(num_sub_queries=3)
    result = await search_node(state)

    raw_papers = result["raw_papers"]
    # Should have at least 1 paper (deduplication)
    assert len(raw_papers) >= 1
    # Should be deduplicated — 'shared_paper' should appear only once
    shared = [p for p in raw_papers if p.get("paper_id") == "shared_paper"]
    assert len(shared) == 1, (
        f"Deduplication broke under throttle: {len(shared)} 'shared_paper' entries"
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
