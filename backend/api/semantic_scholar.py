"""
Semantic Scholar Graph API 客户端
https://api.semanticscholar.org/graph/v1

当 API_MOCK=true 时返回内置 mock 数据（无网络也能跑通）。
"""
import asyncio
import logging
import os
import httpx
from backend.config import SEMANTIC_SCHOLAR_API_KEY, API_MOCK
from backend.utils.runtime_mode import is_runtime_mock  # R10.5.20: 前端可切 mock/real
from backend.models.paper import Paper
from backend.api.mock_data import get_mock_papers, get_all_mock_papers, mark_as_expanded
from backend.api._retry import _get_with_retry  # Round N SIMPLIFY: 抽到共享 helper
from backend.utils.circuit_breaker import CircuitOpenError, ss_breaker  # Fix-X8
from backend.utils.proxy import aget_proxy  # R10.5.96 (F-010): async 版探测
from backend.utils.scrub import scrub_sensitive  # VULN-004
# Round 6 SIMPLIFY: 抽 log_throttle 到 utils, 消除 SS/OA 重复 _should_log 实现 (26 行)
from backend.utils.log_throttle import should_log

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "paperId,title,abstract,year,authors,citationCount,venue,externalIds,url,references"
BATCH_FIELDS = "paperId,title,abstract,year,authors,citationCount,venue,externalIds,url,references"
HEADERS = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
TIMEOUT = 30.0

# NEW-001 修复：模块级 AsyncClient 单例 + 禁用 async with（避免 __aexit__ 关闭连接池）
# 正确用法：client = await _get_client()  →  await client.get(...)
# 在 FastAPI shutdown lifespan 中统一 aclose()
#
# DISABLE_HTTP_POOL 资源泄漏修复：
#   旧实现：_DISABLE_POOL 模式下每次 _get_client() 都新建 httpx.AsyncClient，
#   但返回值未保存到模块状态，close_client() 只能关 _client（永远是 None），
#   临时 client 随函数返回被 Python 引用计数释放，连接池句柄实际泄漏到 GC。
#   新实现：把所有临时 client 记录在 _temporary_clients set，close 时统一 aclose。
_DISABLE_POOL = os.environ.get("DISABLE_HTTP_POOL", "").lower() in ("1", "true", "yes")
_client: httpx.AsyncClient | None = None
_temporary_clients: set[httpx.AsyncClient] = set()


async def _get_client() -> httpx.AsyncClient:
    """async 版 (R10.5.96 F-010): proxy 探测 await aget_proxy, 不阻塞事件循环.

    lifespan 启动期已 run_in_executor 预热, 命中 lru_cache 时 aget_proxy 几乎瞬返.
    """
    global _client
    proxy = await aget_proxy()
    if _DISABLE_POOL:
        # 回滚模式：每次新建 client（无连接池），记录以便 close 时释放
        c = httpx.AsyncClient(timeout=TIMEOUT, proxy=proxy)
        _temporary_clients.add(c)
        return c
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=TIMEOUT,
            proxy=proxy,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )
    return _client


async def close_client() -> None:
    """FastAPI shutdown 调用：释放所有客户端（含 DISABLE_POOL 模式下的临时 client）。"""
    global _client
    # 先关闭所有临时 client
    for c in list(_temporary_clients):
        if not c.is_closed:
            await c.aclose()
    _temporary_clients.clear()
    # 再关闭池化单例
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _mock_fallback(query: str, limit: int) -> list[Paper]:
    """Real 模式失败时降级到 mock，保证流水线不空跑。

    C5 修复：将所有返回的论文标记 is_fallback=True，便于前端区分真实数据
    与 mock 兜底数据，避免用户在 200 响应中误以为拿到真实结果。
    """
    papers = get_mock_papers(query, limit=limit)
    if papers:
        if should_log("ss_fallback"):
            logger.warning(f"[SemanticScholar] fallback to mock for {query[:40]!r}: {len(papers)} papers")
    for p in papers:
        p.is_fallback = True
    return papers


async def search_papers(query: str, limit: int = 50) -> list[Paper]:
    """搜索论文。"""
    if is_runtime_mock():  # R10.5.20: 前端 /admin/runtime-mode 可切, fallback env API_MOCK
        # Mock 模式：返回基于关键词匹配的论文
        papers = get_mock_papers(query, limit=limit)
        # 模拟 API 延迟
        await asyncio.sleep(0.05)
        return papers

    try:
        client = await _get_client()
        resp = await _get_with_retry(
            client,
            f"{BASE_URL}/paper/search",
            params={"query": query, "limit": limit, "fields": PAPER_FIELDS},
            headers=HEADERS,
            breaker=ss_breaker,  # Fix-X8: 3 失败 → 30s 熔断
        )
        if resp.status_code != 200:
            if should_log(f"ss_search_{resp.status_code}"):
                logger.warning(f"[SemanticScholar] search error {resp.status_code}: {query[:60]}")
            # 失败降级：仍返回 mock 数据，避免 8 节点流水线空跑
            return _mock_fallback(query, limit)
        data = resp.json()
    except CircuitOpenError:
        # Fix-X8: 熔断器 OPEN, 立即降级, 不再 hang 30s 等 retry
        if should_log("ss_search_breaker_open"):
            logger.warning(f"[SemanticScholar] circuit OPEN, immediate mock fallback: {query[:60]}")
        return _mock_fallback(query, limit)
    except Exception as e:
        if should_log("ss_search_exception"):
            logger.warning(f"[SemanticScholar] search exception: {scrub_sensitive(str(e))}  → 降级到 mock")
        return _mock_fallback(query, limit)

    papers = []
    for item in data.get("data", []):
        if not item.get("paperId") or not item.get("title"):
            continue
        doi = ""
        if item.get("externalIds") and isinstance(item["externalIds"], dict):
            doi = item["externalIds"].get("DOI", "") or ""
        paper = Paper(
            paper_id=item["paperId"],
            title=item.get("title", ""),
            abstract=item.get("abstract") or "",
            year=item.get("year") or 0,
            authors=[a.get("name", "") for a in item.get("authors", []) if a.get("name")],
            citation_count=item.get("citationCount") or 0,
            venue=item.get("venue") or "",
            doi=doi,
            url=item.get("url") or f"https://www.semanticscholar.org/paper/{item['paperId']}",
            source="semantic_scholar",
        )
        # 解析 references 字段（已在 PAPER_FIELDS 中请求）
        refs = item.get("references") or []
        if refs:
            ref_ids = []
            for r in refs:
                if isinstance(r, dict) and r.get("paperId"):
                    ref_ids.append(r["paperId"])
            if ref_ids:
                paper.references = ref_ids
        papers.append(paper)
    return papers


async def get_references(paper_id: str, limit: int = 30) -> list[Paper]:
    """获取一篇论文的参考文献列表（backward citations: 该论文引用了谁）。"""
    if is_runtime_mock():  # R10.5.20: 前端 /admin/runtime-mode 可切, fallback env API_MOCK
        await asyncio.sleep(0.03)
        # 在 mock 数据里找这个 paper，然后返回它存的 references
        all_papers = get_all_mock_papers()
        target = next((p for p in all_papers if p.paper_id == paper_id), None)
        if not target:
            return []
        ref_ids = target.__dict__.get("references", [])
        refs = []
        for rid in ref_ids[:limit]:
            ref_paper = next((p for p in all_papers if p.paper_id == rid), None)
            if ref_paper:
                refs.append(mark_as_expanded(ref_paper))
        return refs

    try:
        client = await _get_client()
        resp = await _get_with_retry(
            client,
            f"{BASE_URL}/paper/{paper_id}/references",
            params={"fields": BATCH_FIELDS, "limit": limit},
            headers=HEADERS,
            breaker=ss_breaker,  # Fix-X8
        )
        if resp.status_code != 200:
            if should_log(f"ss_refs_{resp.status_code}"):
                logger.warning(f"[SemanticScholar] refs {paper_id} status {resp.status_code}")
            return []
        data = resp.json()
    except Exception as e:
        if should_log("ss_refs_exception"):
            logger.warning(f"[SemanticScholar] refs exception: {scrub_sensitive(str(e))}")
        return []

    papers = []
    for item in data.get("data", []):
        cited = item.get("citedPaper", {})
        if not cited or not cited.get("paperId") or not cited.get("title"):
            continue
        doi = ""
        if cited.get("externalIds") and isinstance(cited["externalIds"], dict):
            doi = cited["externalIds"].get("DOI", "") or ""
        papers.append(Paper(
            paper_id=cited["paperId"],
            title=cited.get("title", ""),
            abstract=cited.get("abstract") or "",
            year=cited.get("year") or 0,
            authors=[a.get("name", "") for a in cited.get("authors", []) if a.get("name")],
            citation_count=cited.get("citationCount") or 0,
            venue=cited.get("venue") or "",
            doi=doi,
            url=cited.get("url") or f"https://www.semanticscholar.org/paper/{cited['paperId']}",
            source="semantic_scholar",
            is_expanded=True,
        ))
    return papers


async def get_citations(paper_id: str, limit: int = 20) -> list[Paper]:
    """获取引用了一篇论文的论文列表（forward citations: 谁引用了这篇论文）。

    犀利评论 #8 修复：补充前向引文扩展路径，避免"Matthew effect"——高引论文的
    references 通常是 5-10 年前的，缺少 2025/2026 的最新 preprints。
    """
    if is_runtime_mock():  # R10.5.20: 前端 /admin/runtime-mode 可切, fallback env API_MOCK
        await asyncio.sleep(0.03)
        # 在 mock 数据里找这个 paper
        all_papers = get_all_mock_papers()
        target = next((p for p in all_papers if p.paper_id == paper_id), None)
        if not target:
            return []
        # 找所有引用了这个 paper 的论文（即把它们放在自己的 references 里）
        citers: list[Paper] = []
        for other in all_papers:
            if other.paper_id == paper_id:
                continue
            other_refs = other.__dict__.get("references", [])
            if paper_id in other_refs:
                citers.append(mark_as_expanded(other))
                if len(citers) >= limit:
                    break
        return citers

    try:
        client = await _get_client()
        resp = await _get_with_retry(
            client,
            f"{BASE_URL}/paper/{paper_id}/citations",
            params={"fields": BATCH_FIELDS, "limit": limit},
            headers=HEADERS,
            breaker=ss_breaker,  # Fix-X8
        )
        if resp.status_code != 200:
            if should_log(f"ss_citations_{resp.status_code}"):
                logger.warning(f"[SemanticScholar] citations {paper_id} status {resp.status_code}")
            return []
        data = resp.json()
    except Exception as e:
        if should_log("ss_citations_exception"):
            logger.warning(f"[SemanticScholar] citations exception: {scrub_sensitive(str(e))}")
        return []

    papers = []
    for item in data.get("data", []):
        citing = item.get("citingPaper", {})
        if not citing or not citing.get("paperId") or not citing.get("title"):
            continue
        doi = ""
        if citing.get("externalIds") and isinstance(citing["externalIds"], dict):
            doi = citing["externalIds"].get("DOI", "") or ""
        papers.append(Paper(
            paper_id=citing["paperId"],
            title=citing.get("title", ""),
            abstract=citing.get("abstract") or "",
            year=citing.get("year") or 0,
            authors=[a.get("name", "") for a in citing.get("authors", []) if a.get("name")],
            citation_count=citing.get("citationCount") or 0,
            venue=citing.get("venue") or "",
            doi=doi,
            url=citing.get("url") or f"https://www.semanticscholar.org/paper/{citing['paperId']}",
            source="semantic_scholar",
            is_expanded=True,
        ))
    return papers
