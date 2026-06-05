"""
Semantic Scholar Graph API 客户端
https://api.semanticscholar.org/graph/v1

当 API_MOCK=true 时返回内置 mock 数据（无网络也能跑通）。
"""
import asyncio
import os
import httpx
from backend.config import SEMANTIC_SCHOLAR_API_KEY, API_MOCK
from backend.models.paper import Paper
from backend.api.mock_data import get_mock_papers, get_all_mock_papers, mark_as_expanded
from backend.utils.proxy import get_proxy  # PERF-002 / B-002
from backend.utils.scrub import scrub_sensitive  # VULN-004

BASE_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "paperId,title,abstract,year,authors,citationCount,venue,externalIds,url,references"
BATCH_FIELDS = "paperId,title,abstract,year,authors,citationCount,venue,externalIds,url,references"
HEADERS = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
TIMEOUT = 30.0
MAX_RETRIES = 2

# NEW-001 修复：模块级 AsyncClient 单例 + 禁用 async with（避免 __aexit__ 关闭连接池）
# 正确用法：client = _get_client()  →  await client.get(...)
# 在 FastAPI shutdown lifespan 中统一 aclose()
_DISABLE_POOL = os.environ.get("DISABLE_HTTP_POOL", "").lower() in ("1", "true", "yes")
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _DISABLE_POOL:
        # 回滚模式：每次新建 client（无连接池）
        return httpx.AsyncClient(timeout=TIMEOUT, proxy=get_proxy())
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=TIMEOUT,
            proxy=get_proxy(),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )
    return _client


async def close_client() -> None:
    """FastAPI shutdown 调用：释放连接池。"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _mock_fallback(query: str, limit: int) -> list[Paper]:
    """Real 模式失败时降级到 mock，保证流水线不空跑。"""
    papers = get_mock_papers(query, limit=limit)
    if papers:
        print(f"[SemanticScholar] fallback to mock for {query[:40]!r}: {len(papers)} papers")
    return papers


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict, headers: dict) -> httpx.Response:
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue
            return resp
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(0.3 * (2 ** attempt))
                continue
            raise
    if last_exc:
        raise last_exc
    return resp


async def search_papers(query: str, limit: int = 50) -> list[Paper]:
    """搜索论文。"""
    if API_MOCK:
        # Mock 模式：返回基于关键词匹配的论文
        papers = get_mock_papers(query, limit=limit)
        # 模拟 API 延迟
        await asyncio.sleep(0.05)
        return papers

    try:
        client = _get_client()
        resp = await _get_with_retry(
            client,
            f"{BASE_URL}/paper/search",
            params={"query": query, "limit": limit, "fields": PAPER_FIELDS},
            headers=HEADERS,
        )
        if resp.status_code != 200:
            print(f"[SemanticScholar] search error {resp.status_code}: {query[:60]}")
            # 失败降级：仍返回 mock 数据，避免 8 节点流水线空跑
            return _mock_fallback(query, limit)
        data = resp.json()
    except Exception as e:
        print(f"[SemanticScholar] search exception: {scrub_sensitive(str(e))}  → 降级到 mock")
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
    if API_MOCK:
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
        client = _get_client()
        resp = await _get_with_retry(
            client,
            f"{BASE_URL}/paper/{paper_id}/references",
            params={"fields": BATCH_FIELDS, "limit": limit},
            headers=HEADERS,
        )
        if resp.status_code != 200:
            print(f"[SemanticScholar] refs {paper_id} status {resp.status_code}")
            return []
        data = resp.json()
    except Exception as e:
        print(f"[SemanticScholar] refs exception: {scrub_sensitive(str(e))}")
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
    if API_MOCK:
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
        client = _get_client()
        resp = await _get_with_retry(
            client,
            f"{BASE_URL}/paper/{paper_id}/citations",
            params={"fields": BATCH_FIELDS, "limit": limit},
            headers=HEADERS,
        )
        if resp.status_code != 200:
            print(f"[SemanticScholar] citations {paper_id} status {resp.status_code}")
            return []
        data = resp.json()
    except Exception as e:
        print(f"[SemanticScholar] citations exception: {scrub_sensitive(str(e))}")
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
