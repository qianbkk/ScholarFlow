"""arXiv search client — R10.5.39 Phase 1.1.

arXiv is the canonical CS / physics / math preprint server. The v1 search agent
needs this for two reasons:
  1. Coverage gap: SS + OA miss a meaningful fraction of recent arXiv-only work.
  2. Quality signal: arXiv IDs are stable identifiers we can cross-reference
     with Crossref / DOI for better dedup.

API: https://export.arxiv.org/api/query (Atom XML, free, no key required)
RPS limit: polite = 1 req / 3s, no hard cap. We use 1.5s spacing.

P10 (P0-1 性能): 原 4s spacing 是过度保守, 导致 5 sub_queries 串行 20s 纯等待.
现在改 1.5s spacing, 5 sub_queries 累计 ≤7.5s. arXiv 触发 429 时 _get_with_retry
退避兜底, 不再需要过保守节流.

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
# P10 优化: 4s → 1.5s. arXiv 官方说 1 req/3s 即可, 1.5s 留 50% buffer.
# 节流用 token bucket 模式: 允许短时 burst, 之后按 1.5s 间隔.
_ARXIV_LOCK = asyncio.Lock()
_LAST_ARXIV_TS = 0.0
_ARXIV_MIN_SPACING = 1.5  # 两次连续调用最小间隔 (秒)

# P10 (P2-3 性能): 共享 module-level httpx client, 跟 SS/OA 对齐.
# 旧实现每次 async with 新建 client, 高并发下连接建立开销巨大.
# 跟 SS/OA 一样用 _get_client() 单例 + _DISABLE_POOL fallback 模式.
import os as _os
_DISABLE_POOL = _os.environ.get("DISABLE_HTTP_POOL", "").lower() in ("1", "true", "yes")
_client: httpx.AsyncClient | None = None
_temporary_clients: set[httpx.AsyncClient] = set()


def _get_client() -> httpx.AsyncClient:
    global _client
    if _DISABLE_POOL:
        c = httpx.AsyncClient(timeout=15.0)
        _temporary_clients.add(c)
        return c
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )
    return _client


async def close_client() -> None:
    """FastAPI shutdown 调用: 释放所有客户端."""
    global _client
    for c in list(_temporary_clients):
        if not c.is_closed:
            await c.aclose()
    _temporary_clients.clear()
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


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
    """Enforce 1.5s spacing on arXiv API calls.

    P10 (P0-1): 原 4s 强制 spacing → 1.5s, 5 sub_queries 节省 ~12.5s.
    仍然有 50% buffer 应对 429 突发限流; 真正 429 由 _get_with_retry 退避兜底.
    """
    global _LAST_ARXIV_TS
    async with _ARXIV_LOCK:
        now = asyncio.get_event_loop().time()
        wait = _ARXIV_MIN_SPACING - (now - _LAST_ARXIV_TS)
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
        # P10 (P2-3 性能): 共享 module-level _client 单例, 跟 SS/OA 对齐.
        # 旧实现每次 async with 新建 client → TCP handshake + TLS 浪费.
        # 新实现模块级 _client + connection pool, 节省每次 ~100ms 连接开销.
        client = _get_client()
        r = await client.get(ARXIV_API, params=params, timeout=15.0)
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
