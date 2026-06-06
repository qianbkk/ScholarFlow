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
from backend.utils.proxy import get_proxy  # PERF-002 / B-002
from backend.utils.scrub import scrub_sensitive  # VULN-004

BASE_URL = "https://api.openalex.org"
TIMEOUT = 30.0
SELECT_FIELDS = "id,title,abstract_inverted_index,publication_year,authorships,cited_by_count,primary_location,doi,referenced_works"
MAX_RETRIES = 2

# NEW-001 修复：模块级 AsyncClient 单例 + 不用 async with
#
# DISABLE_HTTP_POOL 资源泄漏修复：临时 client 记录到 _temporary_clients，
# close 时统一 aclose（详见 semantic_scholar.py 同名修复注释）。
_DISABLE_POOL = os.environ.get("DISABLE_HTTP_POOL", "").lower() in ("1", "true", "yes")
_client: httpx.AsyncClient | None = None
_temporary_clients: set[httpx.AsyncClient] = set()


def _get_client() -> httpx.AsyncClient:
    global _client
    if _DISABLE_POOL:
        # 回滚模式：每次新建 client（无连接池），记录以便 close 时释放
        c = httpx.AsyncClient(timeout=TIMEOUT, proxy=get_proxy())
        _temporary_clients.add(c)
        return c
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
    """FastAPI shutdown 调用：释放所有客户端（含 DISABLE_POOL 模式下的临时 client）。"""
    global _client
    for c in list(_temporary_clients):
        if not c.is_closed:
            await c.aclose()
    _temporary_clients.clear()
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _mock_fallback(query: str, limit: int) -> list[Paper]:
    """Real 模式失败时降级到 mock。

    C5 修复：将所有返回的论文标记 is_fallback=True，便于前端区分真实数据
    与 mock 兜底数据，避免用户在 200 响应中误以为拿到真实结果。
    """
    all_papers = get_mock_papers(query, limit=limit * 2)
    papers = [p for p in all_papers if p.source == "openalex"][:limit]
    for p in papers:
        p.is_fallback = True
    return papers


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex 摘要以倒排索引存储，需重建为原文。

    P1 bug 修复：旧实现用 `positions[i] for i in sorted(positions)`，遇到位置间隙
    (e.g. inverted_index={"AI":[0,2],"model":[1]} —— pos 0,2 有、pos 1 跳了)
    会 KeyError 抛异常。空 `inverted_index` 或 `inverted_index=None` 已被前置检查
    拦截，但位置稀疏的索引会直接 500 整个 /search 流程。

    修复：取 max position 后按 range 顺序 join，间隙用空字符串占位。这样：
      - 不会 KeyError（任何稀疏索引都能跑通）
      - 语义"尽量完整" —— OpenAlex 数据通常无间隙，占位串在 gap 处会被
        上游 search 过滤（len(abstract) > 0 仍成立）
      - 多次出现的 word 仍按 positions 分散到对应位置
    """
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    if not positions:
        return ""
    max_pos = max(positions.keys())
    return " ".join(positions.get(i, "") for i in range(max_pos + 1))


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
        client = _get_client()
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
        print(f"[OpenAlex] search exception: {scrub_sensitive(str(e))}  → 降级到 mock")
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
            paper.references = [r for r in refs if isinstance(r, str)]
        papers.append(paper)
    return papers
