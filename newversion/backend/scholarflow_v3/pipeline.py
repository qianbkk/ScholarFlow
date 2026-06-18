"""v3 research pipeline.

8 nodes, in order: decompose → refine → search → score → extract → gap →
critique → synthesize.

Each node receives the running `State` dict and returns a partial update.
The pipeline is generator-based: `run_pipeline` yields StreamEvent objects
on every node boundary, then yields a final SearchResult.

This is a deterministic mock pipeline — no LLM is called. Each node
synthesizes plausible outputs from a small in-memory corpus. The shape of
the events and result matches what the v3 frontend expects.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from .models import (
    CitationGraph,
    GraphLink,
    GraphMetadata,
    GraphNode,
    Paper,
    SearchRequest,
    SearchResult,
    StreamEvent,
)

PIPELINE_NODES = [
    ("query_decomposer", "Decompose"),
    ("query_refiner", "Refine"),
    ("paper_searcher", "Search"),
    ("relevance_scorer", "Score"),
    ("evidence_extractor", "Extract"),
    ("gap_analyzer", "Gap"),
    ("critic", "Critique"),
    ("synthesis", "Synthesize"),
]


@dataclass
class State:
    query: str
    max_papers: int
    top_k: int
    budget_usd: float
    search_id: str
    started_at: float = field(default_factory=time.time)
    iteration: int = 0
    decomposed: list[str] = field(default_factory=list)
    refined_query: str = ""
    papers: list[Paper] = field(default_factory=list)
    papers_scored: list[Paper] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    critique: str = ""
    report: str = ""
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    is_degraded: bool = False
    fallback_count: int = 0


# ---------- In-memory corpus (deterministic, hash-seeded) ----------

_CORPUS = [
    {
        "id": "ss_001_attention",
        "title": "Attention Is All You Need",
        "year": 2017,
        "authors": ["A. Vaswani", "N. Shazeer", "N. Parmar", "J. Uszkoreit"],
        "venue": "NeurIPS",
        "citations": 110000,
        "abstract": "We propose the Transformer, a novel network architecture based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
        "source": "semantic_scholar",
    },
    {
        "id": "ss_002_bert",
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "year": 2018,
        "authors": ["J. Devlin", "M.-W. Chang", "K. Lee", "K. Toutanova"],
        "venue": "NAACL",
        "citations": 85000,
        "abstract": "We introduce a new language representation model called BERT, which stands for Bidirectional Encoder Representations from Transformers.",
        "source": "semantic_scholar",
    },
    {
        "id": "ss_003_gpt3",
        "title": "Language Models are Few-Shot Learners",
        "year": 2020,
        "authors": ["T. B. Brown", "B. Mann", "N. Ryder"],
        "venue": "NeurIPS",
        "citations": 32000,
        "abstract": "We train GPT-3, an autoregressive language model with 175 billion parameters, and test its performance in few-shot settings.",
        "source": "semantic_scholar",
    },
    {
        "id": "oa_001_alphafold",
        "title": "Highly Accurate Protein Structure Prediction with AlphaFold",
        "year": 2021,
        "authors": ["J. Jumper", "R. Evans", "A. Pritzel"],
        "venue": "Nature",
        "citations": 22000,
        "abstract": "We provide the first computational method that can regularly predict protein structures with atomic accuracy.",
        "source": "openalex",
    },
    {
        "id": "oa_002_diffusion",
        "title": "Denoising Diffusion Probabilistic Models",
        "year": 2020,
        "authors": ["J. Ho", "A. Jain", "P. Abbeel"],
        "venue": "NeurIPS",
        "citations": 18000,
        "abstract": "We present high quality image synthesis results using diffusion probabilistic models, a class of latent variable models inspired by nonequilibrium thermodynamics.",
        "source": "openalex",
    },
    {
        "id": "ss_004_rlhf",
        "title": "Training Language Models to Follow Instructions with Human Feedback",
        "year": 2022,
        "authors": ["L. Ouyang", "J. Wu", "X. Jiang"],
        "venue": "NeurIPS",
        "citations": 9500,
        "abstract": "We show that a 1.3B-parameter InstructGPT model, fine-tuned with human feedback, is preferred to outputs from a 175B GPT-3 model.",
        "source": "semantic_scholar",
    },
    {
        "id": "oa_003_mixture",
        "title": "Mixture-of-Experts Scaling Laws",
        "year": 2024,
        "authors": ["S. Chen", "Z. Lin", "Y. Wang"],
        "venue": "ICML",
        "citations": 410,
        "abstract": "We investigate the scaling behavior of Mixture-of-Experts architectures and find that they exhibit different loss-compute trade-offs than dense models.",
        "source": "openalex",
    },
    {
        "id": "ss_005_chainofthought",
        "title": "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        "year": 2022,
        "authors": ["J. Wei", "X. Wang", "D. Schuurmans"],
        "venue": "NeurIPS",
        "citations": 7800,
        "abstract": "We explore how generating a chain of thought — a series of intermediate reasoning steps — significantly improves the ability of large language models to perform complex reasoning.",
        "source": "semantic_scholar",
    },
    {
        "id": "oa_004_retrieval",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "year": 2020,
        "authors": ["P. Lewis", "E. Perez", "A. Piktus"],
        "venue": "NeurIPS",
        "citations": 12000,
        "abstract": "We develop a general-purpose fine-tuning recipe for RAG — models which combine a pre-trained parametric memory with a non-parametric memory accessed via a dense retriever.",
        "source": "openalex",
    },
    {
        "id": "ss_006_emergent",
        "title": "Emergent Abilities of Large Language Models",
        "year": 2022,
        "authors": ["J. Wei", "Y. Tay", "R. Bommasani"],
        "venue": "TMLR",
        "citations": 3400,
        "abstract": "We discuss emergent abilities of large language models — abilities that are not present in smaller models but are present in larger models.",
        "source": "semantic_scholar",
    },
    {
        "id": "ss_007_toolformer",
        "title": "Toolformer: Language Models Can Teach Themselves to Use Tools",
        "year": 2023,
        "authors": ["T. Schick", "J. Dwivedi-Yu", "R. Dessì"],
        "venue": "NeurIPS",
        "citations": 2200,
        "abstract": "We show that language models can teach themselves to use external tools via simple APIs, achieving substantially improved performance on a variety of tasks.",
        "source": "semantic_scholar",
    },
    {
        "id": "oa_005_longcontext",
        "title": "Lost in the Middle: How Language Models Use Long Contexts",
        "year": 2023,
        "authors": ["N. F. Liu", "K. Lin", "J. Hewitt"],
        "venue": "TMLR",
        "citations": 1600,
        "abstract": "We analyze how language models use long input contexts. We find that performance can degrade significantly when information is located in the middle of the context window.",
        "source": "openalex",
    },
]


def _seed_for(query: str) -> random.Random:
    digest = hashlib.sha256(query.lower().strip().encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _corpus_relevant(query: str, max_papers: int) -> list[dict]:
    """Return corpus items roughly relevant to the query, deterministically."""
    rng = _seed_for(query)
    pool = _CORPUS.copy()
    rng.shuffle(pool)
    n = min(max_papers + 2, len(pool))
    return pool[:n]


# ---------- Node implementations ----------

async def node_decompose(s: State, emit) -> None:
    """Break the query into 2-4 sub-questions."""
    await asyncio.sleep(0.3)
    q = s.query.strip()
    # Deterministic sub-questions based on query shape.
    s.decomposed = [
        f"What is the current state of {q}?",
        f"What are the key open problems in {q}?",
        f"How does {q} compare to alternative approaches?",
    ][: min(4, 2 + len(q) % 3)]
    s.refined_query = q
    s.iteration += 1
    s.total_tokens += 80
    s.total_cost_usd += 0.0002
    emit("log", {"node": "query_decomposer", "sub_questions": s.decomposed})


async def node_refine(s: State, emit) -> None:
    """Refine the query for retrieval — strip filler, expand acronyms."""
    await asyncio.sleep(0.3)
    s.refined_query = s.query.strip().rstrip("?.")
    s.total_tokens += 60
    s.total_cost_usd += 0.0001
    emit("log", {"node": "query_refiner", "refined": s.refined_query})


async def node_search(s: State, emit) -> None:
    """Search the corpus for candidate papers."""
    await asyncio.sleep(0.5)
    raw = _corpus_relevant(s.refined_query or s.query, s.max_papers)
    rng = _seed_for(s.refined_query or s.query)
    for r in raw:
        # Re-rank with deterministic noise on relevance.
        base_rel = rng.uniform(0.55, 0.98)
        paper = Paper(
            paper_id=r["id"],
            title=r["title"],
            abstract=r["abstract"],
            year=r["year"],
            authors=r["authors"],
            citation_count=r["citations"],
            venue=r["venue"],
            url=f"https://example.org/p/{r['id']}",
            doi=f"10.0000/{r['id']}",
            source=r["source"],
            relevance_score=base_rel,
            final_score=base_rel,
        )
        s.papers.append(paper)
    # First emit paper list so the UI can render incrementally.
    emit("papers", {"papers": [p.model_dump() for p in s.papers]})
    s.total_tokens += 220
    s.total_cost_usd += 0.0003
    emit("log", {"node": "paper_searcher", "found": len(s.papers)})


async def node_score(s: State, emit) -> None:
    """Score and rank papers by final score = 0.6*relevance + 0.3*authority + 0.1*recency."""
    await asyncio.sleep(0.4)
    rng = _seed_for((s.refined_query or s.query) + ":score")
    now_year = 2026
    for p in s.papers:
        authority = min(1.0, (p.citation_count / 100000.0) ** 0.5)
        recency = max(0.0, 1.0 - (now_year - p.year) / 20.0)
        jitter = rng.uniform(-0.05, 0.05)
        p.final_score = max(0.0, 0.6 * p.relevance_score + 0.3 * authority + 0.1 * recency + jitter)
        p.relevance_score = round(p.relevance_score, 4)
        p.final_score = round(p.final_score, 4)
    s.papers_scored = sorted(s.papers, key=lambda p: p.final_score, reverse=True)[: s.top_k]
    s.papers = s.papers_scored
    emit("ranked", {"papers": [p.model_dump() for p in s.papers]})
    s.total_tokens += 180
    s.total_cost_usd += 0.0002
    emit("log", {"node": "relevance_scorer", "kept": len(s.papers)})


async def node_extract(s: State, emit) -> None:
    """Extract evidence sentences from each paper's abstract."""
    await asyncio.sleep(0.5)
    for p in s.papers:
        sentences = [s.strip() for s in p.abstract.split(". ") if s.strip()][:2]
        s.evidence[p.paper_id] = sentences
    s.total_tokens += 320
    s.total_cost_usd += 0.0004
    emit("log", {"node": "evidence_extractor", "papers": len(s.evidence)})


async def node_gap(s: State, emit) -> None:
    """Identify gaps in coverage."""
    await asyncio.sleep(0.3)
    years = [p.year for p in s.papers if p.year > 0]
    if years:
        span = max(years) - min(years)
        s.gaps = [
            f"Coverage spans {span} years ({min(years)}-{max(years)})",
            f"Top venue: {max(set(p.venue for p in s.papers), key=lambda v: sum(1 for p in s.papers if p.venue == v))}",
        ]
    else:
        s.gaps = ["No year data available."]
    s.total_tokens += 90
    s.total_cost_usd += 0.0001
    emit("log", {"node": "gap_analyzer", "gaps": s.gaps})


async def node_critique(s: State, emit) -> None:
    """Critique the candidate set — surface caveats."""
    await asyncio.sleep(0.4)
    n = len(s.papers)
    avg_year = sum(p.year for p in s.papers) / max(1, n)
    s.critique = (
        f"{n} papers selected. Median citation count "
        f"{sorted(p.citation_count for p in s.papers)[n // 2]:,}. "
        f"Average publication year {avg_year:.1f}. "
        f"Coverage is {('broad' if n >= 8 else 'narrow')}. "
        f"Reviewers should weigh recency against citation count for hot vs. established work."
    )
    s.total_tokens += 140
    s.total_cost_usd += 0.0002
    emit("critique", {"text": s.critique})


async def node_synthesize(s: State, emit) -> None:
    """Synthesize the report."""
    await asyncio.sleep(0.6)
    cited = s.papers
    parts: list[str] = []
    parts.append(f"# {s.query.strip().rstrip('?')}")
    parts.append(
        f"This report synthesizes findings from {len(cited)} peer-reviewed papers "
        f"retrieved and scored by an 8-node multi-agent pipeline. The literature "
        f"is organized below by contribution, with inline citations to the ranked set."
    )
    parts.append("## Key findings")
    for i, p in enumerate(cited[: min(6, len(cited))], start=1):
        ev = s.evidence.get(p.paper_id, [""])[0]
        parts.append(f"- {p.title}. {ev} [paper_id:{p.paper_id}]")
    if s.gaps:
        parts.append("## Gaps in coverage")
        for g in s.gaps:
            parts.append(f"- {g}")
    if s.critique:
        parts.append("## Critique")
        parts.append(s.critique)
    parts.append("## Method")
    parts.append(
        "Papers were decomposed into sub-questions, retrieved from a small in-memory corpus, "
        "scored by 0.6 relevance + 0.3 authority + 0.1 recency, and synthesized with the original query as the framing axis."
    )
    s.report = "\n\n".join(parts)
    s.total_tokens += 540
    s.total_cost_usd += 0.0006
    emit("log", {"node": "synthesis", "tokens": s.total_tokens})


NODES = [
    node_decompose,
    node_refine,
    node_search,
    node_score,
    node_extract,
    node_gap,
    node_critique,
    node_synthesize,
]


def _build_citation_graph(state: State) -> CitationGraph:
    """Build a citation graph where each paper links to the next by venue / year adjacency."""
    if not state.papers:
        return CitationGraph(
            nodes=[],
            links=[],
            metadata=GraphMetadata(
                total_papers=0,
                total_links=0,
                query=state.query,
            ),
        )

    # Deterministic edge generation: each paper cites the next one (by year desc)
    # and 1 co-cited link per paper.
    by_year = sorted(state.papers, key=lambda p: (-p.year, p.paper_id))
    rng = _seed_for((state.query or "") + ":graph")
    nodes: list[GraphNode] = []
    id_to_idx: dict[str, int] = {}
    for i, p in enumerate(state.papers):
        id_to_idx[p.paper_id] = i
        # size scales with citations, color_value is the year
        size = 4 + min(14, p.citation_count ** 0.5 / 6)
        nodes.append(
            GraphNode(
                id=p.paper_id,
                index=i,
                title=p.title,
                year=p.year,
                citation_count=p.citation_count,
                relevance_score=p.relevance_score,
                final_score=p.final_score,
                size=round(size, 2),
                color_value=float(p.year),
                venue=p.venue,
                authors=p.authors,
                in_degree=0,
                out_degree=0,
                community_id=(i % 3),
            )
        )

    links: list[GraphLink] = []
    link_counts: dict[str, int] = {"cites": 0, "co_cited": 0, "same_venue": 0, "author_overlap": 0}
    for i, p in enumerate(state.papers):
        # cite: each paper cites the one immediately after it in the list
        for j, q in enumerate(state.papers):
            if p.paper_id == q.paper_id:
                continue
            if j == i + 1:
                links.append(GraphLink(source=p.paper_id, target=q.paper_id, type="cites"))
                link_counts["cites"] += 1
        # same_venue: a single link to one other paper in the same venue
        for j, q in enumerate(state.papers):
            if i >= j or q.venue != p.venue or not p.venue:
                continue
            links.append(GraphLink(source=p.paper_id, target=q.paper_id, type="same_venue"))
            link_counts["same_venue"] += 1
            break
    # Compute in/out degree
    for link in links:
        src_idx = id_to_idx.get(link.source)
        tgt_idx = id_to_idx.get(link.target)
        if src_idx is not None:
            nodes[src_idx].out_degree += 1
        if tgt_idx is not None:
            nodes[tgt_idx].in_degree += 1

    years = [n.year for n in nodes if n.year > 0]
    year_range = [min(years), max(years)] if years else None
    return CitationGraph(
        nodes=nodes,
        links=links,
        metadata=GraphMetadata(
            total_papers=len(nodes),
            total_links=len(links),
            query=state.query,
            year_range=year_range,
            community_count=3,
            link_type_counts=link_counts,
        ),
    )


async def run_pipeline(req: SearchRequest, search_id: str) -> AsyncIterator[StreamEvent | SearchResult]:
    """Run the 8-node pipeline. Yields StreamEvent on node boundaries, then a final SearchResult."""
    state = State(
        query=req.query,
        max_papers=req.max_papers,
        top_k=req.top_k,
        budget_usd=req.budget_usd,
        search_id=search_id,
    )

    # Each node receives this emit() and can fire events mid-execution.
    # We queue them and yield them after the node finishes (so the v3
    # frontend always sees node_start ... node events ... node_end as a
    # strict sequence).
    pending: list[StreamEvent] = []

    def emit(event: str, data: dict) -> None:
        pending.append(StreamEvent(event=event, data=data, ts=time.time(), search_id=search_id))

    def make_event(event: str, data: dict) -> StreamEvent:
        return StreamEvent(event=event, data=data, ts=time.time(), search_id=search_id)

    for i, (node_id, label) in enumerate(PIPELINE_NODES):
        yield make_event("node_start", {"node_id": node_id, "label": label, "index": i})
        try:
            await NODES[i](state, emit)
            while pending:
                yield pending.pop(0)
            yield make_event("node_end", {"node_id": node_id, "label": label, "ok": True})
        except Exception as exc:
            yield make_event("node_end", {"node_id": node_id, "label": label, "ok": False, "error": str(exc)})
            state.is_degraded = True
        # Live cost + token update after each node.
        yield make_event("cost", {"cost_usd": state.total_cost_usd, "tokens": state.total_tokens})

    graph = _build_citation_graph(state)
    elapsed = time.time() - state.started_at
    result = SearchResult(
        search_id=search_id,
        query=state.query,
        report=state.report,
        ranked_papers=state.papers,
        citation_graph=graph,
        total_cost_usd=round(state.total_cost_usd, 6),
        total_tokens=state.total_tokens,
        iteration=state.iteration,
        status="complete" if not state.is_degraded else "partial",
        elapsed_seconds=round(elapsed, 2),
        is_degraded=state.is_degraded,
        fallback_paper_count=state.fallback_count,
    )
    yield result
