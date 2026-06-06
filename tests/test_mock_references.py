"""Fix 1: Mock papers must have references so D3 graph has edges in demo mode.

The mock dataset is used when API_MOCK is enabled.  Prior to the fix,
mock papers were constructed without populating the `references` field,
so the citation graph built by graph_builder.py was always empty
(zero edges -> 孤立节点).  This test guards against regression.

The test verifies:
  1. At least 5 mock papers have non-empty `references` lists.
  2. The graph built from the top 20 mock papers has at least 3 edges.
"""
import pytest

from backend.api import mock_data
from backend.agents import graph_builder
from backend.models.paper import Paper


def _build_state_from_mock_papers(papers: list[Paper]) -> dict:
    """Wrap mock papers into the SearchState shape expected by build_graph_node."""
    return {
        "original_query": "",
        "sub_queries": [],
        "raw_papers": [p.to_dict() for p in papers],
        "expanded_papers": [p.to_dict() for p in papers],
        "ranked_papers": [p.to_dict() for p in papers],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 3,
        "expanded_paper_ids": [],
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 5.0,
        "model_usage": {},
        "status": "graphing",
        "error": None,
    }


def test_mock_papers_have_reference_graph():
    """At least 5 mock papers have non-empty refs AND the graph has >= 3 edges."""
    # Pull the top 20 mock papers (same path as production get_mock_papers(''))
    papers = mock_data.get_mock_papers("", limit=20)
    assert len(papers) >= 5, f"expected at least 5 mock papers, got {len(papers)}"

    # Assertion 1: at least 5 mock papers have non-empty references lists
    papers_with_refs = [p for p in papers if p.references]
    assert len(papers_with_refs) >= 5, (
        f"expected at least 5 mock papers with non-empty references, "
        f"got {len(papers_with_refs)}"
    )

    # Build the graph the way graph_builder does it
    state = _build_state_from_mock_papers(papers)
    new_state = graph_builder.build_graph_node(state)
    links = new_state["citation_graph"].get("links", [])

    # Assertion 2: graph has at least 3 edges
    assert len(links) >= 3, (
        f"expected at least 3 citation edges in the demo graph, got {len(links)}"
    )
