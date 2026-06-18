"""Pipeline state — minimal common shape shared between v1 + v3 backends.

Both implementations agree on these 4 fields. v1 extends via
backend.models.state.SearchState; v3 extends via newversion's local
State dataclass. Future agents can extend this TypedDict as the two
backends converge.
"""
from typing import Literal, TypedDict


# The 8 pipeline nodes executed in order by the v3 mock backend and
# (under slightly different names) by v1's LangGraph state machine.
NodeId = Literal[
    "query_decomposer",
    "query_refiner",
    "paper_searcher",
    "relevance_scorer",
    "evidence_extractor",
    "gap_analyzer",
    "critic",
    "synthesis",
]


class PipelineState(TypedDict):
    """Minimal shared state — only fields both backends use verbatim."""

    query: str
    iteration: int
    status: str
    error: str | None