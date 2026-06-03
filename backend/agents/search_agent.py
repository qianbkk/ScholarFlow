"""
节点 ② — 多源并行检索
并发调用 Semantic Scholar + OpenAlex，合并去重。
"""
import asyncio
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar, openalex
from backend.utils.text_utils import deduplicate_papers


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
            print(f"[SearchAgent] task exception: {type(result).__name__}: {result}")
            continue
        if isinstance(result, list):
            all_papers.extend(result)

    # 过滤无摘要论文
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique_papers = deduplicate_papers(all_papers)

    # 第二轮及以后：与已有论文合并
    iteration = state.get("iteration", 0)
    if iteration > 0:
        existing_dicts = state.get("expanded_papers") or state.get("ranked_papers") or state.get("raw_papers") or []
        if existing_dicts:
            existing_papers = []
            for d in existing_dicts:
                try:
                    existing_papers.append(Paper(**d))
                except Exception:
                    continue
            unique_papers = deduplicate_papers(existing_papers + unique_papers)

    print(f"[SearchAgent] iter={iteration} | sub_queries={len(sub_queries)} | unique={len(unique_papers)}")

    return {
        **state,
        "raw_papers": [p.to_dict() for p in unique_papers],
        "status": "expanding",
    }
