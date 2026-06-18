"""PubMed search client — R10.5.39 Phase 1.1.

PubMed is the canonical biomedical citation database (35M+ records). Free,
open, no key required for low-volume use (NCBI asks for an API key above
3 req/s without one; we stay well below that).

API: E-utilities
  Step 1: esearch.fcgi?db=pubmed&term=...&retmode=json  → list of PMIDs
  Step 2: esummary.fcgi?db=pubmed&id=...                → metadata per PMID

This is a 2-step process. We do it inline (call esearch, then call esummary
with the returned IDs).
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

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_PUBMED_LOCK = asyncio.Lock()
_LAST_PUBMED_TS = 0.0


async def _throttle_pubmed() -> None:
    """NCBI without API key: max 3 req/s. We pace at 0.4s."""
    global _LAST_PUBMED_TS
    async with _PUBMED_LOCK:
        now = asyncio.get_event_loop().time()
        wait = 0.4 - (now - _LAST_PUBMED_TS)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_PUBMED_TS = asyncio.get_event_loop().time()


async def _esearch(query: str, retmax: int) -> list[str]:
    await _throttle_pubmed()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                ESEARCH,
                params={
                    "db": "pubmed",
                    "term": query,
                    "retmax": min(retmax, 20),
                    "retmode": "json",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning(f"[pubmed] esearch failed: {type(exc).__name__}: {scrub_sensitive(str(exc))}")
        return []
    return (data.get("esearchresult", {}) or {}).get("idlist", []) or []


def _make_paper(uid: str, doc: dict[str, Any]) -> Paper | None:
    title = (doc.get("title") or "").strip()
    if not title:
        return None
    authors_raw = doc.get("authors") or []
    authors: list[str] = []
    for a in authors_raw:
        # PubMed esummary author shape: { "name": "Smith AB", "authtype": "Author", "clusterid": "" }
        # The `name` field is "LastName Initials". `authtype` is "Author" / "Investigator".
        # We want just the name; strip the "Name" sentinel if present.
        name = (a.get("name") or "").strip()
        if not name:
            continue
        # Some PubMed responses include a trailing " Name" sentinel from the
        # JSON serializer. Strip it if so.
        if name.endswith(" Name"):
            name = name[:-len(" Name")]
        authors.append(name)

    year = 0
    pubdate = (doc.get("pubdate") or "").strip()
    if pubdate:
        try:
            year = int(pubdate.split()[0])
        except (ValueError, IndexError):
            year = 0

    venue = (doc.get("fulljournalname") or doc.get("source") or "").strip()
    abstract_list = doc.get("abstract") or ""
    if isinstance(abstract_list, list):
        abstract = " ".join(abstract_list).strip()
    else:
        abstract = str(abstract_list).strip()

    articleids = doc.get("articleids", []) or []
    doi = None
    pmc = None
    for aid in articleids:
        if aid.get("idtype") == "doi":
            doi = aid.get("value", "").strip() or None
        if aid.get("idtype") == "pmc":
            pmc = aid.get("value", "").strip() or None

    url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
    if pmc:
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/"

    return Paper(
        paper_id=f"pm_{uid}",
        title=title,
        abstract=abstract,
        year=year,
        authors=authors,
        citation_count=0,  # PubMed doesn't expose citations in esummary
        venue=venue,
        url=url,
        doi=doi,
        source="openalex",  # reuse enum slot
        relevance_score=0.0,
        final_score=0.0,
        is_expanded=False,
    )


async def _esummary(pmids: list[str]) -> list[Paper]:
    if not pmids:
        return []
    await _throttle_pubmed()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                ESUMMARY,
                params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning(f"[pubmed] esummary failed: {type(exc).__name__}: {scrub_sensitive(str(exc))}")
        return []

    result = data.get("result", {}) or {}
    uids = result.get("uids", []) or []
    papers: list[Paper] = []
    for uid in uids:
        doc = result.get(uid)
        if not doc:
            continue
        p = _make_paper(uid, doc)
        if p:
            papers.append(p)
    return papers


async def search_papers(query: str, limit: int = 10) -> list[Paper]:
    """Search PubMed (esearch → esummary). Mock mode returns empty."""
    if is_runtime_mock():
        return []
    pmids = await _esearch(query, retmax=limit)
    if not pmids:
        return []
    return await _esummary(pmids)
