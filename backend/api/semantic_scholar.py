"""
Semantic Scholar Graph API 客户端
https://api.semanticscholar.org/graph/v1

当 API_MOCK=true 时返回内置 mock 数据（无网络也能跑通）。
"""
import asyncio
import httpx
from backend.config import SEMANTIC_SCHOLAR_API_KEY, API_MOCK
from backend.models.paper import Paper
from backend.api.mock_data import get_mock_papers, get_all_mock_papers, mark_as_expanded

BASE_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "paperId,title,abstract,year,authors,citationCount,venue,externalIds,url"
BATCH_FIELDS = "paperId,title,abstract,year,authors,citationCount,venue,externalIds,url"
HEADERS = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
TIMEOUT = 30.0
MAX_RETRIES = 2


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
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await _get_with_retry(
                client,
                f"{BASE_URL}/paper/search",
                params={"query": query, "limit": limit, "fields": PAPER_FIELDS},
                headers=HEADERS,
            )
            if resp.status_code != 200:
                print(f"[SemanticScholar] search error {resp.status_code}: {query[:60]}")
                return []
            data = resp.json()
    except Exception as e:
        print(f"[SemanticScholar] search exception: {e}")
        return []

    papers = []
    for item in data.get("data", []):
        if not item.get("paperId") or not item.get("title"):
            continue
        doi = ""
        if item.get("externalIds") and isinstance(item["externalIds"], dict):
            doi = item["externalIds"].get("DOI", "") or ""
        papers.append(Paper(
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
        ))
    return papers


async def get_references(paper_id: str, limit: int = 30) -> list[Paper]:
    """获取一篇论文的参考文献列表。"""
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
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
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
        print(f"[SemanticScholar] refs exception: {e}")
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
