"""
节点 ⑦ — 引文知识图谱构建
纯计算，无 LLM 调用，输出 D3.js 可渲染的 nodes/links。
"""
import math
from backend.models.state import SearchState


def build_graph_node(state: SearchState) -> SearchState:
    """构建 D3.js 可渲染的引文关系图数据（无 LLM 调用）。"""

    ranked = (state.get("ranked_papers") or [])[:20]
    node_id_set = {p.get("paper_id", "") for p in ranked if p.get("paper_id")}

    nodes = []
    for i, p in enumerate(ranked):
        pid = p.get("paper_id") or f"paper_{i}"
        cites = p.get("citation_count", 0) or 0
        rel = p.get("relevance_score", 5.0) or 0.0

        nodes.append({
            "id": pid,
            "index": i,
            "title": p.get("title", "Unknown"),
            "year": p.get("year", 0),
            "citation_count": cites,
            "relevance_score": rel,
            "final_score": p.get("final_score", 0),
            "url": p.get("url", ""),
            "abstract": (p.get("abstract", "") or "")[:250],
            "source": p.get("source", ""),
            "is_expanded": p.get("is_expanded", False),
            "venue": p.get("venue", ""),
            "authors": p.get("authors", []),
            "size": round(8 + min(27, math.log1p(cites) * 3.5), 1),
            "color_value": round(min(1.0, max(0.0, rel / 10.0)), 2),
        })

    # 构建引用边：节点之间的引用关系
    links = []
    for p in ranked:
        source_id = p.get("paper_id", "")
        if not source_id:
            continue
        for ref_id in (p.get("references", []) or []):
            if not ref_id:
                continue
            if ref_id in node_id_set and ref_id != source_id:
                links.append({
                    "source": source_id,
                    "target": ref_id,
                    "type": "cites",
                })

    graph = {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "total_papers": len(nodes),
            "total_links": len(links),
            "query": state.get("original_query", ""),
            "search_iterations": state.get("iteration", 0),
        },
    }

    return {**state, "citation_graph": graph, "status": "done"}
