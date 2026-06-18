"""Crossref search client — R10.5.39 Phase 1.1.

Crossref is the canonical DOI registry. Free, open, no key required. Useful
because it covers the long tail of small-publisher work that SS / OA miss.

API: https://api.crossref.org/works?query.bibliographic=...
Rate limit: polite pool = 50 req/s. We use 1s spacing for politeness.

Response is JSON. We map Crossref's "work" shape into our Paper model.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.models.paper import Paper
from backend.utils.runtime_mode import is_runtime_mock
from backend.utils.scrub import scrub_sensitive

logger = logging.getLogger(__name__)

CROSSREF_API = "https://api.crossref.org/works"
_CROSSREF_LOCK = asyncio.Lock()
_LAST_CROSSREF_TS = 0.0


async def _throttle_crossref() -> None:
    global _LAST_CROSSREF_TS
    async with _CROSSREF_LOCK:
        now = asyncio.get_event_loop().time()
        wait = 1.0 - (now - _LAST_CROSSREF_TS)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_CROSSREF_TS = asyncio.get_event_loop().time()


def _make_paper(item: dict[str, Any]) -> Paper | None:
    title_list = item.get("title") or []
    if not title_list:
        return None
    title = " ".join(title_list[0].split())

    abstract = (item.get("abstract") or "").strip()
    # Crossref abstracts often contain JATS XML; strip tags if so.
    if abstract.startswith("<"):
        import re
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    doi = item.get("DOI")
    url = f"https://doi.org/{doi}" if doi else (item.get("URL") or "")

    year = 0
    for date_field in ("published-print", "published-online", "issued", "created"):
        date = item.get(date_field, {}).get("date-parts", [[None]])[0]
        if date and date[0]:
            try:
                year = int(date[0])
                break
            except (ValueError, TypeError):
                continue

    authors = []
    for a in item.get("author", []):
        name = " ".join(p for p in [a.get("given"), a.get("family")] if p).strip()
        if name:
            authors.append(name)

    venue_parts = []
    for ct in item.get("container-title", [])[:1]:
        venue_parts.append(ct)
    for pub in item.get("publisher", [])[:1]:
        venue_parts.append(pub)
    venue = " · ".join(venue_parts) if venue_parts else ""

    # Crossref doesn't expose a real-time citation count; use references count as proxy
    citation_count = len(item.get("reference", []) or [])

    is_referenced_by = item.get("is-referenced-by-count", 0) or 0
    if is_referenced_by:
        citation_count = is_referenced_by

    paper_id = f"cr_{doi.replace('/', '_')}" if doi else f"cr_{title[:32]}"

    return Paper(
        paper_id=paper_id,
        title=title,
        abstract=abstract,
        year=year,
        authors=authors,
        citation_count=citation_count,
        venue=venue,
        url=url,
        doi=doi,
        source="openalex",  # reuse enum slot
        relevance_score=0.0,
        final_score=0.0,
        is_expanded=False,
    )


async def search_papers(query: str, limit: int = 10) -> list[Paper]:
    """Search Crossref. Mock mode returns empty."""
    if is_runtime_mock():
        return []

    await _throttle_crossref()
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "ScholarFlow/1.0 (mailto:qianbkk@example.com)"},
        ) as client:
            r = await client.get(
                CROSSREF_API,
                params={"query.bibliographic": query, "rows": min(limit, 20)},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning(f"[crossref] query failed: {type(exc).__name__}: {scrub_sensitive(str(exc))}")
        return []

    papers: list[Paper] = []
    for item in (data.get("message", {}) or {}).get("items", []):
        p = _make_paper(item)
        if p:
            papers.append(p)
    return papers
