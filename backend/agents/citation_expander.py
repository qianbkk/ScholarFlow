"""
节点 ③ — 引文网络扩展
获取高引用论文的参考文献，扩展候选池。
关键修复：把"谁引用了谁"的关系写回 Paper.references，供图谱构建使用。
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

    # ===== 关键修复：构建 seed_to_refs 反向映射 =====
    seed_to_refs: dict[str, list[str]] = {}
    for seed_paper, result in zip(top, refs_results):
        if isinstance(result, list):
            ref_ids = [r.paper_id for r in result if r.paper_id]
            if ref_ids:
                seed_to_refs[seed_paper.paper_id] = ref_ids

    all_papers: list[Paper] = list(raw)
    new_refs = 0
    for result in refs_results:
        if isinstance(result, Exception):
            print(f"[CitationExpander] refs exception: {type(result).__name__}: {result}")
            continue
        if isinstance(result, list):
            new_refs += len(result)
            all_papers.extend(result)

    # ===== 关键修复：把"seed -> refs"关系写回每篇 seed paper 的 references 字段 =====
    for p in all_papers:
        if p.paper_id in seed_to_refs:
            p.references = seed_to_refs[p.paper_id]

    # 过滤 + 去重
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique = deduplicate_papers(all_papers)

    # 统计实际有引文边的论文数
    n_with_edges = sum(1 for p in unique if p.references)
    print(
        f"[CitationExpander] {len(raw)} -> {len(unique)} papers "
        f"(+{new_refs} refs from top {len(top)} seeds, "
        f"{n_with_edges} papers have outgoing edges)"
    )

    return {
        **state,
        "expanded_papers": [p.to_dict() for p in unique],
        "status": "ranking",
    }
