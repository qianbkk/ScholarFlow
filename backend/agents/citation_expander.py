"""
节点 ③ — 引文网络扩展
获取高引用论文的参考文献，扩展候选池。
"""
import asyncio
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar
from backend.utils.text_utils import deduplicate_papers


async def expand_citations_node(state: SearchState) -> SearchState:
    """获取高引用论文的参考文献，扩展候选池。"""

    raw_dicts = state.get("raw_papers") or []
    raw: list[Paper] = []
    for d in raw_dicts:
        try:
            raw.append(Paper(**d))
        except Exception:
            continue

    if not raw:
        return {**state, "expanded_papers": [], "status": "ranking"}

    # 选引用数最高的前 5 篇做引文扩展（只用 SS，有结构化引用数据）
    ss_papers = [p for p in raw if p.source == "semantic_scholar" and p.paper_id]
    top = sorted(ss_papers, key=lambda p: p.citation_count, reverse=True)[:5]

    if not top:
        # 没有 SS 论文也能继续：直接把 raw 作为 expanded
        return {
            **state,
            "expanded_papers": [p.to_dict() for p in raw],
            "status": "ranking",
        }

    tasks = [semantic_scholar.get_references(p.paper_id, limit=20) for p in top]
    refs_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers: list[Paper] = list(raw)
    new_refs = 0
    for result in refs_results:
        if isinstance(result, Exception):
            print(f"[CitationExpander] refs exception: {type(result).__name__}: {result}")
            continue
        if isinstance(result, list):
            new_refs += len(result)
            all_papers.extend(result)

    # 过滤 + 去重
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique = deduplicate_papers(all_papers)

    print(f"[CitationExpander] {len(raw)} -> {len(unique)} papers (+{new_refs} refs from top {len(top)} seeds)")

    return {
        **state,
        "expanded_papers": [p.to_dict() for p in unique],
        "status": "ranking",
    }
