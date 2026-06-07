"""
节点 ⑦ — 引文知识图谱构建
纯计算，无 LLM 调用，输出 D3.js 可渲染的 nodes/links。

M-18 重构 (P0 节点 metadata + 4 类边 + 社区发现 + 时间分层):
- 节点新增: in_degree / out_degree / pagerank (用归一化 in_degree 近似) / community_id (按 decade 分组)
- 边新增 3 类: co_cited (被同一 paper 引用) / same_venue (同会议/期刊) / author_overlap (共同作者)
- metadata 新增: year_range / link_type_counts / community_count
"""
import math
from collections import defaultdict
from backend.models.state import SearchState


def build_graph_node(state: SearchState) -> SearchState:
    """构建 D3.js 可渲染的引文关系图数据（无 LLM 调用）。"""

    # FIX: 统一 ranked 论文数为 25 — 与 ranker_agent / synthesis_agent 对齐
    # 旧 [:20] 丢掉了 ranker 评出的 21-25 名论文（暗物质）。
    ranked = (state.get("ranked_papers") or [])[:25]
    node_id_set = {p.get("paper_id", "") for p in ranked if p.get("paper_id")}

    # ===== M-18: 计算 4 类边的边集合 =====
    # 类 1: cites (直接引用, 已有)
    cites_edges: set[tuple[str, str]] = set()
    for p in ranked:
        source_id = p.get("paper_id", "")
        if not source_id:
            continue
        for ref_id in (p.get("references", []) or []):
            if ref_id and ref_id in node_id_set and ref_id != source_id:
                cites_edges.add((source_id, ref_id))

    # 类 2: co_cited (被同一 paper 引用 — 表语义关联)
    # 算法: 找 ranked 中有共同 references 的两个节点, 加 co_cited 边 (sample top-10, 避免 n²)
    node_to_refs: dict[str, set[str]] = defaultdict(set)
    for p in ranked:
        pid = p.get("paper_id", "")
        if not pid:
            continue
        for ref_id in (p.get("references", []) or []):
            if ref_id in node_id_set:
                node_to_refs[pid].add(ref_id)

    co_cited_pairs: set[tuple[str, str]] = set()
    pids = list(node_to_refs.keys())
    for i, a in enumerate(pids):
        for b in pids[i + 1 : i + 11]:  # 只跟后 10 个节点比, 避免 n²
            shared = node_to_refs[a] & node_to_refs[b]
            if len(shared) >= 2:  # 至少 2 个共同引用才算 co-cited
                co_cited_pairs.add((a, b))

    # 类 3: same_venue (同会议/期刊, 学术社交信号)
    venue_to_pids: dict[str, list[str]] = defaultdict(list)
    for p in ranked:
        pid = p.get("paper_id", "")
        venue = (p.get("venue", "") or "").strip().lower()
        if pid and venue:
            venue_to_pids[venue].append(pid)

    same_venue_pairs: set[tuple[str, str]] = set()
    for venue, pids_in_venue in venue_to_pids.items():
        if len(pids_in_venue) >= 2 and len(pids_in_venue) <= 6:  # 大 venue 太宽, 不画
            for i, a in enumerate(pids_in_venue):
                for b in pids_in_venue[i + 1 :]:
                    same_venue_pairs.add(tuple(sorted((a, b))))

    # 类 4: author_overlap (共同作者)
    pid_to_authors: dict[str, set[str]] = defaultdict(set)
    for p in ranked:
        pid = p.get("paper_id", "")
        authors = set(a.lower() for a in (p.get("authors", []) or []) if a)
        if pid and authors:
            pid_to_authors[pid] = authors

    author_overlap_pairs: set[tuple[str, str]] = set()
    pids2 = list(pid_to_authors.keys())
    for i, a in enumerate(pids2):
        for b in pids2[i + 1 : i + 11]:
            shared = pid_to_authors[a] & pid_to_authors[b]
            if shared:
                author_overlap_pairs.add(tuple(sorted((a, b))))

    # ===== M-18: 节点 metadata (in/out_degree, pagerank 近似, community_id) =====
    # pagerank 简化: 归一化 in_degree (引用入度)
    # community_id 简化: decade 分组 (1970s/1980s/.../2020s)
    years = [p.get("year", 0) or 0 for p in ranked]
    year_min = min((y for y in years if y > 0), default=2020)
    year_max = max(years, default=2024)

    nodes = []
    for i, p in enumerate(ranked):
        pid = p.get("paper_id") or f"paper_{i}"
        cites = p.get("citation_count", 0) or 0
        rel = p.get("relevance_score", 5.0) or 0.0
        year = p.get("year", 0) or 0

        # in_degree (被引次数, 在 ranked 子图内)
        in_degree = sum(1 for (s, t) in cites_edges if t == pid)
        out_degree = sum(1 for (s, t) in cites_edges if s == pid)
        # pagerank 简化: 归一化入度, max in_degree 视为 1.0
        # (R11 跟 NetworkX 一起做真实 PageRank)
        all_in_degrees = []
        for p2 in ranked:
            pid2 = p2.get("paper_id", "")
            all_in_degrees.append(
                sum(1 for (s, t) in cites_edges if t == pid2) if pid2 else 0
            )
        max_in = max(all_in_degrees) if all_in_degrees else 1
        pagerank = round(in_degree / max_in, 3) if max_in else 0.0

        # community_id: decade 分组 (e.g. 2020s → 5)
        if year > 0:
            decade = (year // 10) * 10
            community_id = decade - (year_min // 10) * 10  # 0-indexed
        else:
            community_id = 0

        nodes.append({
            "id": pid,
            "index": i,
            "title": p.get("title", "Unknown"),
            "year": year,
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
            # M-18 新增
            "in_degree": in_degree,
            "out_degree": out_degree,
            "pagerank": pagerank,
            "community_id": community_id,
        })

    # ===== 合并所有边类型 =====
    links = []
    for s, t in cites_edges:
        links.append({"source": s, "target": t, "type": "cites"})
    for a, b in co_cited_pairs:
        links.append({"source": a, "target": b, "type": "co_cited"})
    for a, b in same_venue_pairs:
        links.append({"source": a, "target": b, "type": "same_venue"})
    for a, b in author_overlap_pairs:
        links.append({"source": a, "target": b, "type": "author_overlap"})

    # ===== M-18: link type counts + community count =====
    link_type_counts: dict[str, int] = defaultdict(int)
    for l in links:
        link_type_counts[l["type"]] += 1
    community_count = len({n["community_id"] for n in nodes})

    graph = {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "total_papers": len(nodes),
            "total_links": len(links),
            "query": state.get("original_query", ""),
            "search_iterations": state.get("iteration", 0),
            # M-18 新增
            "year_range": [year_min, year_max],
            "link_type_counts": dict(link_type_counts),
            "community_count": community_count,
        },
    }

    return {**state, "citation_graph": graph, "status": "done"}
