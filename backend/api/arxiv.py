"""arXiv search client — R10.5.39 Phase 1.1.

arXiv is the canonical CS / physics / math preprint server. The v1 search agent
needs this for two reasons:
  1. Coverage gap: SS + OA miss a meaningful fraction of recent arXiv-only work.
  2. Quality signal: arXiv IDs are stable identifiers we can cross-reference
     with Crossref / DOI for better dedup.

API: https://export.arxiv.org/api/query (Atom XML, free, no key required)
RPS limit: polite = 1 req / 3s, no hard cap. We use 4s spacing.

The response is Atom XML; we parse with stdlib ElementTree (no extra dep).
"""
from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from backend.models.paper import Paper
from backend.utils.runtime_mode import is_runtime_mock
from backend.utils.scrub import scrub_sensitive

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
# Polite spacing. arXiv asks for 1 req/3s, we use 4s for safety.
_ARXIV_LOCK = asyncio.Lock()
_LAST_ARXIV_TS = 0.0


def _make_paper(entry: ET.Element) -> Paper | None:
    """Convert an Atom <entry> into our Paper model."""
    title_el = entry.find("atom:title", ARXIV_NS)
    if title_el is None or not title_el.text:
        return None
    title = " ".join(title_el.text.split())  # collapse whitespace

    summary_el = entry.find("atom:summary", ARXIV_NS)
    abstract = (summary_el.text or "").strip() if summary_el is not None else ""

    id_el = entry.find("atom:id", ARXIV_NS)
    arxiv_url = (id_el.text or "").strip() if id_el is not None else ""
    # http://arxiv.org/abs/2401.01234v1 -> 2401.01234
    arxiv_id = arxiv_url.rsplit("/", 1)[-1].split("v")[0] if arxiv_url else ""

    year = 0
    published_el = entry.find("atom:published", ARXIV_NS)
    if published_el is not None and published_el.text:
        try:
            year = int(published_el.text[:4])
        except (ValueError, IndexError):
            year = 0

    authors = []
    for a in entry.findall("atom:author/atom:name", ARXIV_NS):
        if a.text:
            authors.append(a.text.strip())

    doi = None
    doi_el = entry.find("arxiv:doi", ARXIV_NS)
    if doi_el is not None and doi_el.text:
        doi = doi_el.text.strip()

    venue = "arXiv"
    journal_ref_el = entry.find("arxiv:journal_ref", ARXIV_NS)
    if journal_ref_el is not None and journal_ref_el.text:
        venue = journal_ref_el.text.strip()

    return Paper(
        paper_id=f"arxiv_{arxiv_id}" if arxiv_id else f"arxiv_{title[:32]}",
        title=title,
        abstract=abstract,
        year=year,
        authors=authors,
        citation_count=0,  # arXiv doesn't expose citation count
        venue=venue,
        url=arxiv_url,
        doi=doi,
        source="openalex",  # reuse enum slot; frontend filters by source
        relevance_score=0.0,
        final_score=0.0,
        is_expanded=False,
    )


async def _throttle_arxiv() -> None:
    """Enforce 4s spacing on arXiv API calls."""
    global _LAST_ARXIV_TS
    async with _ARXIV_LOCK:
        now = asyncio.get_event_loop().time()
        wait = 4.0 - (now - _LAST_ARXIV_TS)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_ARXIV_TS = asyncio.get_event_loop().time()


async def search_papers(query: str, limit: int = 10) -> list[Paper]:
    """Search arXiv. Mock mode returns an empty list (no arXiv in mock_data)."""
    if is_runtime_mock():
        return []

    await _throttle_arxiv()

    params: dict[str, Any] = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": min(limit, 20),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(ARXIV_API, params=params)
            r.raise_for_status()
    except Exception as exc:
        logger.warning(f"[arxiv] query failed: {type(exc).__name__}: {scrub_sensitive(str(exc))}")
        return []

    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as exc:
        logger.warning(f"[arxiv] XML parse failed: {exc}")
        return []

    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        p = _make_paper(entry)
        if p:
            papers.append(p)
    return papers
