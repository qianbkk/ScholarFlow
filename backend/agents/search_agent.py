"""
节点 ② — 多源并行检索
并发调用 Semantic Scholar + OpenAlex，合并去重。

Round 2 PERF-004 修复：search_node 加 Semaphore(4)，与 citation_expander 配合控制 SS 限流。
单次 refine 循环最多 5 迭代 × 5 子查询 = 25 次 SS 调用 (×2 OpenAlex = 50 总请求)，
无 Semaphore 时单次 gather 即触发 10 并发 + 多轮 429 风险。
Semaphore(4) 把单批并发峰值从 10 降到 4，对齐 citation_expander 的 _CITATION_SEMAPHORE 限额。
"""
import asyncio
import logging
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar, openalex
from backend.utils.text_utils import deduplicate_papers
from backend.utils.scrub import scrub_sensitive  # VULN-004

logger = logging.getLogger(__name__)

# ===== SS API 限速：单次 gather 批次并发上限 =====
# SS 免费 tier 100 req/5min。search_node 一次 gather 最多 5 子查询 × 2 源 = 10 并发。
# 限到 4 与 citation_expander._CITATION_SEMAPHORE 对齐，确保
#   - 单批内峰值不超 4
#   - search + citation 两阶段总峰值不超 8 (4+4)
#   - 5 次 refine 迭代累计安全在限流窗口内
_SEARCH_SEMAPHORE = asyncio.Semaphore(4)


async def _throttled_search(coro):
    """包装 SS / OpenAlex 搜索调用，强制走 _SEARCH_SEMAPHORE。"""
    async with _SEARCH_SEMAPHORE:
        return await coro


async def search_node(state: SearchState) -> SearchState:
    """并行调用双源 API，合并去重。"""

    sub_queries = state.get("sub_queries") or []
    if not sub_queries:
        return {**state, "raw_papers": [], "status": "expanding"}

    # 并发搜索：每个子查询同时查两个数据库
    # Round 2 PERF-004: 通过 _throttled_search 走 Semaphore(4) 限流，避免 429
    # Round 6 S2: search_agent limit 30/20 → 15/10, 250→125 papers, 节省 50% SS/OA API 配额
    # (单次 max_iter=3 不再占满 5min 配额)
    tasks = []
    for q in sub_queries:
        tasks.append(_throttled_search(semantic_scholar.search_papers(q, limit=15)))
        tasks.append(_throttled_search(openalex.search_papers(q, limit=10)))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers: list[Paper] = []
    for result in results:
        if isinstance(result, Exception):
            # BUG-002 修复：去掉裸 print，改用 logger
            logger.warning(f"[search_node] task exception: {type(result).__name__}: {scrub_sensitive(str(result))}")
            continue
        if isinstance(result, list):
            all_papers.extend(result)

    # 过滤无摘要论文
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique_papers = deduplicate_papers(all_papers)

    # 第二轮及以后：与已有论文合并
    iteration = state.get("iteration", 0)
    if iteration > 0:
        existing_dicts = state.get("ranked_papers") or state.get("expanded_papers") or state.get("raw_papers") or []
        if existing_dicts:
            existing_papers = []
            for d in existing_dicts:
                try:
                    # BUG-004 修复：使用 from_dict 替代 Paper(**d)
                    existing_papers.append(Paper.from_dict(d))
                except Exception as e:
                    logger.warning(f"[search_node] Paper deserialize failed: {scrub_sensitive(str(e))}, keys={list(d.keys())[:5]}")
                    continue
            unique_papers = deduplicate_papers(existing_papers + unique_papers)

    logger.info(f"[search_node] iter={iteration} | sub_queries={len(sub_queries)} | unique={len(unique_papers)}")

    return {
        **state,
        "raw_papers": [p.to_dict() for p in unique_papers],
        "status": "expanding",
    }
