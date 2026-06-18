"""Pydantic models for the v3 API.

Contract is intentionally compact — the v3 frontend only needs:
  - Paper (id, title, year, authors, venue, citations, source, scores)
  - GraphNode / GraphLink / CitationGraph
  - SearchResult (report + papers + graph + cost + status)
  - StreamEvent (event, data, ts) for SSE

The v3 API does NOT carry v1's verbose model_usage_summary / model_usage
field, BibTeX/RIS, or stream_token — the v3 frontend reads cost/tokens
directly from the live event stream.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class Paper(BaseModel):
    paper_id: str
    title: str
    abstract: str = ""
    year: int = 0
    authors: list[str] = Field(default_factory=list)
    citation_count: int = 0
    venue: str = ""
    url: str = ""
    doi: str | None = None
    source: Literal["semantic_scholar", "openalex", "local_demo", "synthesis"] = "local_demo"
    relevance_score: float = 0.0
    final_score: float = 0.0
    is_expanded: bool = False
    is_fallback: bool = False


class GraphNode(BaseModel):
    id: str
    index: int
    title: str
    year: int
    citation_count: int
    relevance_score: float
    final_score: float
    size: float
    color_value: float
    venue: str = ""
    authors: list[str] = Field(default_factory=list)
    in_degree: int = 0
    out_degree: int = 0
    community_id: int = 0


class GraphLink(BaseModel):
    source: str
    target: str
    type: Literal["cites", "co_cited", "same_venue", "author_overlap"] = "cites"


class GraphMetadata(BaseModel):
    total_papers: int
    total_links: int
    query: str
    year_range: list[int] | None = None
    community_count: int = 0
    link_type_counts: dict[str, int] = Field(default_factory=dict)


class CitationGraph(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
    metadata: GraphMetadata


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_papers: int = Field(default=20, ge=1, le=200)
    top_k: int = Field(default=10, ge=1, le=50)
    budget_usd: float = Field(default=0.50, ge=0.0, le=100.0)


class SearchResult(BaseModel):
    search_id: str
    query: str
    report: str
    ranked_papers: list[Paper]
    citation_graph: CitationGraph
    total_cost_usd: float
    total_tokens: int
    iteration: int
    status: Literal["complete", "partial", "error"]
    elapsed_seconds: float
    is_degraded: bool = False
    fallback_paper_count: int = 0


class StreamEvent(BaseModel):
    event: str
    data: dict
    ts: float
    search_id: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    nodes: int
    uptime_seconds: float
