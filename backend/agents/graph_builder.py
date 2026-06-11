"""
节点 ⑦ — 引文知识图谱构建
纯计算，无 LLM 调用，输出 D3.js 可渲染的 nodes/links。

M-18 重构 (P0 节点 metadata + 4 类边 + 社区发现 + 时间分层):
- 节点新增: in_degree / out_degree / pagerank (用归一化 in_degree 近似) / community_id (按 decade 分组)
- 边新增 3 类: co_cited (被同一 paper 引用) / same_venue (同会议/期刊) / author_overlap (共同作者)
- metadata 新增: year_range / link_type_counts / community_count

R10.5.1 V3-fix (HH.txt 审计 §4): 图谱剪枝, 防止节点爆炸
- 当前 ranked_papers 已 [:25] 截断, 实际最大 25 节点
- 但未来若开放 expanded_papers 进来, MAX_GRAPH_NODES 强制 cap
- 剪枝策略: 保留 (引用数 Top-N) ∪ (相关性 ≥ SCORE_THRESHOLD), 优先满足
- metadata 加 pruned_count, 前端可显示 "隐藏 N 个节点" 提示
"""
import math
import logging
from collections import defaultdict
from backend.models.state import SearchState

logger = logging.getLogger(__name__)

# HH.txt §4 (P2) 防止 D3 渲染灾难的硬上限
# 来源: HH.txt 建议"图谱规模强制控制在 100 节点以内"
# 评分阈值: relevance ≥ 8.0 视为核心节点必保留
MAX_GRAPH_NODES = 100
GRAPH_SCORE_THRESHOLD = 8.0


def detect_communities_modularity(
    node_ids: list[str] | set[str],
    edges: list[tuple[str, str, str]],
) -> dict[str, int]:
    """基于引文网络结构做真实社区发现 (R10.5.7 P1-2, R10.5.8 code-review 修正).

    旧版 community_id 用 decade 分组 (1970s/1980s/...) — 只是按发表时间划
    块, 不是基于引文网络结构. 用户看图谱看不到"研究主题聚类", 失去社区
    发现的核心价值.

    真实实现: 用 networkx.greedy_modularity_communities (Clauset-Newman-Moore
    贪心算法, O(N²logN) 但 N≤100 极快). 边权: cites=3 (最强), co_cited=2,
    same_venue=1, author_overlap=1.

    边界 (R10.5.8 加 warning log, 不再静默退化):
    - N < 3 → 单社区 (避免过分割) + warning
    - 无边 → 单社区 (graph 不连通) + warning
    - networkx 不可用 → 单社区 (兜底) + warning
    - greedy_modularity 抛异常 → 单社区 + warning
    """
    # R10.5.8: node_ids 兼容 list/set, 内部转 set 加速 O(1) 成员检查
    node_id_set = set(node_ids)

    if len(node_id_set) < 3:
        logger.warning(
            f"[graph_builder] community detection skipped: only {len(node_id_set)} nodes "
            f"(need ≥3 for meaningful modularity). Falling back to single community."
        )
        return {nid: 0 for nid in node_id_set}
    try:
        import networkx as nx
    except ImportError:
        logger.warning(
            "[graph_builder] networkx not installed, community detection disabled. "
            "Install via `pip install networkx>=3.0` for real modularity clustering."
        )
        return {nid: 0 for nid in node_id_set}

    G = nx.Graph()
    G.add_nodes_from(node_id_set)
    # 边权: cites=3 (最强结构信号), co_cited=2, same_venue=1, author_overlap=1
    edge_weights = {"cites": 3, "co_cited": 2, "same_venue": 1, "author_overlap": 1}
    for s, t, etype in edges:
        # R10.5.8: O(1) 成员检查 (旧实现 list, O(N) 每次)
        if s in node_id_set and t in node_id_set and s != t:
            w = edge_weights.get(etype, 1)
            if G.has_edge(s, t):
                G[s][t]["weight"] += w
            else:
                G.add_edge(s, t, weight=w)

    if G.number_of_edges() == 0:
        logger.warning(
            "[graph_builder] community detection skipped: no edges in graph. "
            "Falling back to single community."
        )
        return {nid: 0 for nid in node_id_set}

    try:
        communities = nx.community.greedy_modularity_communities(G, weight="weight")
    except Exception as e:
        # R10.5.8: 加 warning, 不再静默
        logger.warning(
            f"[graph_builder] greedy_modularity_communities failed: {type(e).__name__}: {e}. "
            f"Falling back to single community."
        )
        return {nid: 0 for nid in node_id_set}

    result: dict[str, int] = {}
    for cid, members in enumerate(communities):
        for m in members:
            result[m] = cid
    for nid in node_id_set:
        if nid not in result:
            result[nid] = 0
    return result


def apply_graph_pruning(
    ranked_full: list[dict],
    *,
    max_nodes: int = MAX_GRAPH_NODES,
    score_threshold: float = GRAPH_SCORE_THRESHOLD,
) -> list[dict]:
    """HH.txt §4 图谱剪枝策略.

    输入: ranker_agent 评出的全部论文 (可能 25+, 未来若 open expanded 进来可能 50+).
    输出: 剪到 ≤ max_nodes 节点, 同时保证:
      - 引用数 Top-N 全保留 (核心高引论文不被剪)
      - relevance ≥ score_threshold 全保留 (高度相关论文不被剪)
      - 其余按 final_score 降序填充到 max_nodes
      - 永远保留 ranked_papers 中 ranker 已评出的前 25 (上下文完整性)

    当前 ranked_papers 已 [:25] 截断, 所以 len(ranked_full) ≤ 25 几乎不会触发.
    但保留函数以备未来开放 expanded 节点 (R11+).
    """
    if len(ranked_full) <= max_nodes:
        return ranked_full  # 不需要剪

    # 1. 必保留: relevance ≥ score_threshold
    must_keep = [p for p in ranked_full if (p.get("relevance_score", 0) or 0) >= score_threshold]

    # 2. 必保留: 引用数 Top-N (N = max_nodes / 2)
    top_n = max_nodes // 2
    by_cites = sorted(ranked_full, key=lambda p: p.get("citation_count", 0) or 0, reverse=True)
    high_cite = by_cites[:top_n]

    # 3. 合并去重 (preserving original order)
    keep_ids: set[str] = set()
    for p in must_keep + high_cite:
        pid = p.get("paper_id", "")
        if pid:
            keep_ids.add(pid)

    # 4. 剩余按 final_score 降序填充到 max_nodes
    remaining = [p for p in ranked_full if p.get("paper_id", "") not in keep_ids]
    remaining.sort(key=lambda p: p.get("final_score", 0) or 0, reverse=True)
    slots = max(0, max_nodes - len(keep_ids))
    filler = remaining[:slots]

    # 5. 按原始顺序合并
    kept_set = keep_ids | {p.get("paper_id", "") for p in filler}
    return [p for p in ranked_full if p.get("paper_id", "") in kept_set]


def build_graph_node(state: SearchState) -> SearchState:
    """构建 D3.js 可渲染的引文关系图数据（无 LLM 调用）。"""

    # FIX: 统一 ranked 论文数为 25 — 与 ranker_agent / synthesis_agent 对齐
    # 旧 [:20] 丢掉了 ranker 评出的 21-25 名论文（暗物质）。
    ranked_full = (state.get("ranked_papers") or [])
    ranked = apply_graph_pruning(ranked_full, max_nodes=MAX_GRAPH_NODES)
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
    # R10.5.7 P1-2: community_id 改真实社区发现 (networkx.greedy_modularity_communities),
    #                替代旧版按 decade 假分组. 边权 cites=3, co_cited=2, others=1.
    years = [p.get("year", 0) or 0 for p in ranked]
    year_min = min((y for y in years if y > 0), default=2020)
    year_max = max(years, default=2024)

    # P1-3 fix (深度审计 §P1-3): 消除 O(N²×E) pagerank 计算.
    # 旧实现: 内层循环对每个节点都遍历所有 cites_edges 求 in_degree,
    #         加上嵌套外层循环 → 总复杂度 O(N² × E).
    # 新实现: 预计算 in_degree_map (O(E)), 外层循环直接 O(1) 查询.
    in_degree_map: dict[str, int] = defaultdict(int)
    out_degree_map: dict[str, int] = defaultdict(int)
    node_ids = {p.get("paper_id", "") for p in ranked if p.get("paper_id")}
    for s, t in cites_edges:
        if s in node_ids:
            out_degree_map[s] += 1
        if t in node_ids:
            in_degree_map[t] += 1
    max_in = max(in_degree_map.values(), default=1)

    # R10.5.7 P1-2: 真实社区发现 — 用全部 4 类边建 weighted graph,
    # greedy_modularity_communities 检测. 替代旧版 decade 假分组.
    all_edges: list[tuple[str, str, str]] = []
    for s, t in cites_edges:
        all_edges.append((s, t, "cites"))
    for a, b in co_cited_pairs:
        all_edges.append((a, b, "co_cited"))
    for a, b in same_venue_pairs:
        all_edges.append((a, b, "same_venue"))
    for a, b in author_overlap_pairs:
        all_edges.append((a, b, "author_overlap"))
    community_map = detect_communities_modularity(node_ids, all_edges)

    nodes = []
    for i, p in enumerate(ranked):
        pid = p.get("paper_id") or f"paper_{i}"
        cites = p.get("citation_count", 0) or 0
        rel = p.get("relevance_score", 5.0) or 0.0
        year = p.get("year", 0) or 0

        # in_degree (被引次数, 在 ranked 子图内) — O(1) 查表
        in_degree = in_degree_map.get(pid, 0)
        out_degree = out_degree_map.get(pid, 0)
        # pagerank 简化: 归一化入度, max in_degree 视为 1.0
        pagerank = round(in_degree / max_in, 3) if max_in else 0.0

        # community_id: 真实社区发现 (R10.5.7 P1-2), 替代旧 decade 假分组
        community_id = community_map.get(pid, 0)

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
            # R10.5.1 V3-fix: 图谱剪枝 (HH.txt §4 P2 防 D3 渲染灾难)
            "max_graph_nodes": MAX_GRAPH_NODES,
            "pruned_count": max(0, len(ranked_full) - len(ranked)),
        },
    }

    return {**state, "citation_graph": graph, "status": "done"}
