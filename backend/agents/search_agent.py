"""
节点 ② — 多源并行检索
并发调用 Semantic Scholar + OpenAlex，合并去重。
"""
import asyncio
import logging
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar, openalex
from backend.utils.text_utils import deduplicate_papers
from backend.utils.scrub import scrub_sensitive  # VULN-004

logger = logging.getLogger(__name__)


async def search_node(state: SearchState) -> SearchState:
    """并行调用双源 API，合并去重。"""

    sub_queries = state.get("sub_queries") or []
    if not sub_queries:
        return {**state, "raw_papers": [], "status": "expanding"}

    # 并发搜索：每个子查询同时查两个数据库
    tasks = []
    for q in sub_queries:
        tasks.append(semantic_scholar.search_papers(q, limit=30))
        tasks.append(openalex.search_papers(q, limit=20))

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
