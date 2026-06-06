"""Fix 3: search_agent iteration merge should prefer ranked_papers.

When iteration > 0, search_node merges the new raw_papers with the
already-processed set so that previously-seen papers aren't lost.
The merge source priority is critical:

  - expanded_papers can be 50+ (raw + backward + forward citations)
  - ranked_papers is at most 30 and has already been ranked once
  - raw_papers is the first-iteration raw set

Preferring `expanded_papers` (the old behavior) was wrong because:
  1) It inflates the merge pool unnecessarily.
  2) Papers in `ranked_papers` carry stale `relevance_score` /
     `final_score` from the previous ranker pass; merging them
     in can pollute the new ranking.

The fix is to prefer `ranked_papers` first (smaller, top 30, has
had one round of ranking), then fall back to the broader pools.
"""
import asyncio
import pytest

from backend.agents import search_agent
from backend.models.paper import Paper
from backend.models.state import SearchState


def _build_state(ranked_ids, expanded_ids, raw_ids) -> SearchState:
    return {
        "original_query": "test",
        "sub_queries": ["transformer attention"],
        "raw_papers": [{"paper_id": pid, "title": f"raw-{pid}", "abstract": "x" * 100} for pid in raw_ids],
        "expanded_papers": [{"paper_id": pid, "title": f"exp-{pid}", "abstract": "x" * 100} for pid in expanded_ids],
        "ranked_papers": [{"paper_id": pid, "title": f"rank-{pid}", "abstract": "x" * 100} for pid in ranked_ids],
        "report": "",
        "citation_graph": {},
        "iteration": 1,  # iteration > 0 to trigger merge path
        "max_iterations": 3,
        "expanded_paper_ids": [],
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 5.0,
        "model_usage": {},
        "status": "searching",
        "error": None,
    }


def test_iteration_merge_prefers_ranked_papers(monkeypatch):
    """When all 3 fields are populated, merged set should come from ranked_papers first.

    We capture the new raw_papers list written by search_node and assert:
      1) It includes the IDs from `ranked_papers` (priority 1).
      2) It does NOT pull in `expanded_papers`-only IDs that aren't in
         `ranked_papers` (the old behavior would have).
    """
    ranked_ids = ["r1", "r2", "r3"]
    expanded_ids = ["e1", "e2", "e3", "e4"]  # larger pool
    raw_ids = ["raw1", "raw2"]

    state = _build_state(ranked_ids, expanded_ids, raw_ids)

    # Stub out the external API modules so search_node doesn't try to hit them.
    class _EmptyList:
        async def search_papers(self, q, limit=30):
            return []

    # Replace the bound module functions with stubs that always return empty lists.
    monkeypatch.setattr(search_agent.semantic_scholar, "search_papers",
                        lambda q, limit=30: asyncio.sleep(0, result=[]))
    monkeypatch.setattr(search_agent.openalex, "search_papers",
                        lambda q, limit=20: asyncio.sleep(0, result=[]))

    new_state = asyncio.run(search_agent.search_node(state))

    merged_ids = [p["paper_id"] for p in new_state["raw_papers"]]

    # All ranked_papers IDs must be present
    for pid in ranked_ids:
        assert pid in merged_ids, f"ranked_paper {pid} missing from merged set"

    # expanded_papers-only IDs (not in ranked_papers) should NOT be merged in
    # under the new policy (ranked_papers is preferred over expanded_papers).
    expanded_only = set(expanded_ids) - set(ranked_ids)
    for pid in expanded_only:
        assert pid not in merged_ids, (
            f"expanded-only id {pid} leaked into the merge; "
            f"ranked_papers should have been preferred"
        )
