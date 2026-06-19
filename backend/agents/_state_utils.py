"""backend.agents._state_utils
=============================

R10.5.46 (P1 LangGraph safety nets): 跨节点共享的 state 工具函数.

历史:
- R10.5.22: prune_state 写在 query_refiner.py 里, 只在 refine 入口调.
  第一次 pass (query_decompose → search → expand → rank → synthesize)
  没有 state 上限, 长 query 拉满 50 papers 后, raw_papers / expanded_papers
  持续累积 → token 成本失控 + LLM context 截断风险.
- R10.5.46: 抽到 _state_utils.py, 任何节点入口都可以调. search_node
  入口也调一次, 保证第一次 pass 也有 state 上限.

关键函数:
- prune_state(state): 把 raw/expanded/ranked 3 个 paper list 按 relevance
  截到 cap. 已有 relevance_score 的优先, 0 分的保留在尾部 (按原序).
  不修改其他字段 (iteration, status, cost 等保持原样).
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.models.state import SearchState

logger = logging.getLogger(__name__)


# R10.5.22 (U.txt + U2.txt + U3.txt 审计 #2): 跨迭代 state 裁剪.
# 旧实现: raw_papers / expanded_papers / ranked_papers 在 refine 循环里无限累积,
# max_iter=3 时 state 总论文数从 ~50 膨胀到 ~150, 序列化到 SSE 事件 + LLM
# sub_queries 拼接时全部要走一遍, Token 成本 + 内存 + 延迟都线性放大.
# 修复: 入口处按 relevance_score 排序后截到上限, 高相关保留, 噪声裁掉.
# 阈值:
#   - RAW_PAPERS_CAP: SS 原始检索结果, 50 篇足够覆盖多源双 iter
#   - EXPANDED_PAPERS_CAP: 引文扩展, 50 篇 (跟 citation_expander MAX_TOTAL_PAPERS 对齐)
#   - RANKED_PAPERS_CAP: LLM 实际消费的, 30 篇足以喂出高质量综述
RAW_PAPERS_CAP = 50
EXPANDED_PAPERS_CAP = 50
RANKED_PAPERS_CAP = 30


def _prune_papers_by_score(papers: list[dict], cap: int) -> list[dict]:
    """按 relevance_score 降序裁到 cap. 0 分论文也保留 (ranker 跳过情况), 仅按原序.

    这里不复制 state, 直接返回新 list (LangGraph reducer 自然合并).
    """
    if len(papers) <= cap:
        return papers
    # 优先保留有 relevance_score 的, 按分数降序
    with_score = [p for p in papers if (p.get("relevance_score") or 0) > 0]
    without_score = [p for p in papers if (p.get("relevance_score") or 0) <= 0]
    with_score.sort(key=lambda p: p.get("relevance_score", 0), reverse=True)
    return (with_score + without_score)[:cap]


def prune_state(state: SearchState) -> SearchState:
    """R10.5.22 + R10.5.46 (P1): 跨节点 state 裁剪, 防 raw/expanded/ranked 无限累积.

    调用点:
    - R10.5.22: query_refine_node 入口 (loop 内)
    - R10.5.46: search_node 入口 (第一次 pass 也调, 避免长 query 拉满 state)

    不修改 iteration / status / cost, 只把 3 个 paper list 截到上限,
    减少下游 LLM 拼接 + SSE 序列化成本.

    R10.5.51 (/simplify): fast-path 跳过 dict copy. 3 个 list 都不超 cap 时
    直接返原 state, 省一次 dict() 深拷贝 + 3 个 list 检查.
    """
    raw = state.get("raw_papers") or []
    expanded = state.get("expanded_papers") or []
    ranked = state.get("ranked_papers") or []
    # Fast-path: 3 个 list 都没超 cap, 无需拷贝 state
    if (len(raw) <= RAW_PAPERS_CAP
            and len(expanded) <= EXPANDED_PAPERS_CAP
            and len(ranked) <= RANKED_PAPERS_CAP):
        return state
    new_state = dict(state)
    if len(raw) > RAW_PAPERS_CAP:
        new_state["raw_papers"] = _prune_papers_by_score(raw, RAW_PAPERS_CAP)
    if len(expanded) > EXPANDED_PAPERS_CAP:
        new_state["expanded_papers"] = _prune_papers_by_score(expanded, EXPANDED_PAPERS_CAP)
    if len(ranked) > RANKED_PAPERS_CAP:
        new_state["ranked_papers"] = _prune_papers_by_score(ranked, RANKED_PAPERS_CAP)
    # R10.5.51 (/simplify): 用 .get 兜底 — test 可能只传部分字段 (e.g. 只有 ranked)
    logger.debug(
        f"[_state_utils.prune_state] capped: "
        f"raw={len(raw)}->{len(new_state.get('raw_papers', raw))}, "
        f"expanded={len(expanded)}->{len(new_state.get('expanded_papers', expanded))}, "
        f"ranked={len(ranked)}->{len(new_state.get('ranked_papers', ranked))}"
    )
    return new_state  # type: ignore[return-value]
