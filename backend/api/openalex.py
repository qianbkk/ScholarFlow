"""
OpenAlex API 客户端
https://api.openalex.org

当 API_MOCK=true 时返回内置 mock 数据。
"""
import asyncio
import os
import httpx
from backend.config import OPENALEX_EMAIL, API_MOCK
from backend.models.paper import Paper
from backend.api.mock_data import get_mock_papers, get_all_mock_papers

BASE_URL = "https://api.openalex.org"
TIMEOUT = 30.0
SELECT_FIELDS = "id,title,abstract_inverted_index,publication_year,authorships,cited_by_count,primary_location,doi,referenced_works"
MAX_RETRIES = 2


def _mock_fallback(query: str, limit: int) -> list[Paper]:
    """Real 模式失败时降级到 mock。"""
    all_papers = get_mock_papers(query, limit=limit * 2)
    return [p for p in all_papers if p.source == "openalex"][:limit]


def _get_proxy() -> str | None:
    """与 semantic_scholar._get_proxy 保持一致：env → urllib → 本地端口兜底。"""
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(var)
        if v:
            return v
    try:
        import urllib.request
        proxies = urllib.request.getproxies()
        for key in ("https", "http"):
            if key in proxies and proxies[key] and "127.0.0.1" in proxies[key]:
                return proxies[key]
    except Exception:
        pass
    for port in (7890, 7891, 7897, 10809, 1080):
        try:
            import socket
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    return None


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex 摘要以倒排索引存储，需重建为原文。"""
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions))


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(url, params=params)
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
    """通过 OpenAlex 搜索论文。"""
    if API_MOCK:
        await asyncio.sleep(0.05)
        # 优先返回 OpenAlex 源（mock_data 里 source=openalex 的）
        all_papers = get_mock_papers(query, limit=limit * 2)
        return [p for p in all_papers if p.source == "openalex"][:limit]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, proxy=_get_proxy()) as client:
            resp = await _get_with_retry(
                client,
                f"{BASE_URL}/works",
                params={
                    "search": query,
                    "mailto": OPENALEX_EMAIL,
                    "per-page": limit,
                    "select": SELECT_FIELDS,
                    "filter": "has_abstract:true",
                },
            )
            if resp.status_code != 200:
                print(f"[OpenAlex] search error {resp.status_code}: {query[:60]}  → 降级到 mock")
                return _mock_fallback(query, limit)
            data = resp.json()
    except Exception as e:
        print(f"[OpenAlex] search exception: {e}  → 降级到 mock")
        return _mock_fallback(query, limit)

    papers = []
    for item in data.get("results", []):
        venue = ""
        loc = item.get("primary_location") or {}
        src = loc.get("source") or {}
        if isinstance(src, dict):
            venue = src.get("display_name", "") or ""

        abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))
        if not abstract:
            continue

        openalex_id = item.get("id", "")
        if not openalex_id:
            continue

        doi = item.get("doi") or ""
        if doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/"):]

        paper = Paper(
            paper_id=openalex_id,
            title=item.get("title") or "",
            abstract=abstract,
            year=item.get("publication_year") or 0,
            authors=[
                a.get("author", {}).get("display_name", "")
                for a in item.get("authorships", [])
                if isinstance(a, dict) and a.get("author")
            ],
            citation_count=item.get("cited_by_count") or 0,
            venue=venue,
            doi=doi,
            url=openalex_id,
            source="openalex",
        )
        if not paper.title:
            continue
        refs = item.get("referenced_works") or []
        if refs:
            paper.__dict__["references"] = [r for r in refs if isinstance(r, str)]
        papers.append(paper)
    return papers
