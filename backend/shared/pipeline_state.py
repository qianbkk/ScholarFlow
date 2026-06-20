"""Pipeline state — minimal common shape shared across v1 backend modules.

v1 extends via backend.models.state.SearchState. (R10.5.52 cleanup: v3/v4
experimental backend in newversion/ has been deleted, so the "shared between
v1 + v3 backends" framing no longer applies — this TypedDict is now used
only by v1.)
"""
from typing import Literal, TypedDict


# The 8 pipeline nodes executed in order by v1's LangGraph state machine.
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