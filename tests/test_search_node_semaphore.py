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


# ===== 3) Module-level Semaphore exists (defensive) =====

def test_search_node_module_has_semaphore():
    """search_agent module should expose a Semaphore (or similar limiter)."""
    has_sem = False
    for attr_name in dir(search_agent):
        attr = getattr(search_agent, attr_name)
        if isinstance(attr, asyncio.Semaphore):
            has_sem = True
            # Sanity-check the limit
            assert attr._value <= 8, (
                f"Semaphore limit too high: {attr._value}. "
                f"Should match citation_expander (4) or be conservatively small."
            )
            break
    assert has_sem, (
        "PERF-004 FAIL: search_agent module has no asyncio.Semaphore. "
        "Add `_SEARCH_SEMAPHORE = asyncio.Semaphore(4)` and wrap search calls."
    )


# ===== 4) Semaphore limit matches citation_expander (consistency) =====

def test_search_node_semaphore_matches_citation_expander():
    """If both modules have Semaphores, they should have the same limit
    to keep concurrency policy consistent across the pipeline.
    """
    from backend.agents import citation_expander

    search_sem = None
    for attr_name in dir(search_agent):
        attr = getattr(search_agent, attr_name)
        if isinstance(attr, asyncio.Semaphore):
            search_sem = attr
            break

    if search_sem is None:
        pytest.skip("search_agent has no Semaphore (PERF-004 fix may not be applied)")

    cite_sem = getattr(citation_expander, "_CITATION_SEMAPHORE", None)
    if cite_sem is None:
        pytest.skip("citation_expander has no _CITATION_SEMAPHORE")

    assert search_sem._value == cite_sem._value, (
        f"PERF-004: search_node Semaphore limit ({search_sem._value}) must match "
        f"citation_expander Semaphore limit ({cite_sem._value}) for consistent "
        f"concurrency policy."
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
