"""
节点 ④ — 三维质检排序

三维评分（真正独立）：
- 相关性 Relevance (LLM, fast model)        — 论文与查询的语义相关度
- 权威性 Authority (基于引用数规则 + venue  ) — 学术影响力
- 一致性 Consistency (LLM, fast model)        — 论文结论与领域主流观点的对齐度（独立维度）

final = 0.5*rel + 0.3*auth + 0.2*cons

注：早期版本 consistency 是 (rel+auth)/2 估算，存在文档与代码不一致的诚信问题。
本次实现真正调用 LLM 进行一致性评估，并提供 mock 兜底以保证 mock 模式可演示。
"""
import json
import asyncio
import logging
import re
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.utils.llm_client import call_llm, merge_usage_into_state

logger = logging.getLogger(__name__)


# 顶刊 / 顶会权重（用于权威性的 venue 修正）
_VENUE_BONUS = {
    "Nature": 0.5, "Science": 0.5, "JMLR": 0.4, "TPAMI": 0.4,
    "NeurIPS": 0.3, "ICML": 0.3, "ICLR": 0.3, "CVPR": 0.3,
    "ECCV": 0.25, "ICCV": 0.25, "ACL": 0.25, "EMNLP": 0.25,
    "NAACL": 0.2, "WWW": 0.2, "KDD": 0.2, "AAAI": 0.2,
    "AISTATS": 0.15, "CCS": 0.15, "USENIX": 0.15, "SOSP": 0.3,
    "OSDI": 0.3, "ICRA": 0.15, "IROS": 0.15, "MICCAI": 0.2,
    "Interspeech": 0.2, "ICML Workshop": 0.1, "ACL Workshop": 0.1,
}


def _authority_score(citation_count: int, venue: str = "") -> float:
    """基于引用数 + venue 计算权威性（不消耗 token）。"""
    thresholds = [
        (1000, 9.0), (500, 8.5), (200, 8.0), (100, 7.5),
        (50, 7.0), (20, 6.0), (10, 5.0), (5, 4.0), (1, 3.0),
    ]
    base = 2.0
    for threshold, score in thresholds:
        if citation_count >= threshold:
            base = score
            break
    bonus = _VENUE_BONUS.get(venue, 0.0)
    return min(10.0, base + bonus)


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


async def _score_relevance(paper: Paper, query: str) -> tuple[float, dict]:
    """相关性 LLM 评分（独立信号）。"""
    prompt = f"""Rate how relevant this paper is to the research query.

Query: {query}

Paper: {paper.title}
Abstract (first 250 chars): {paper.abstract[:250]}

Respond with JSON only:
{{"relevance": <number 0-10>, "reason": "<one sentence>"}}"""

    text, usage = await call_llm(prompt, task_type="fast_score", max_tokens=80, json_mode=True)
    data = _extract_json_object(text)
    if data and "relevance" in data:
        try:
            score = float(data["relevance"])
            score = max(0.0, min(10.0, score))
        except Exception:
            score = 5.0
    else:
        # 兜底：基于标题关键词重合度
        score = 5.0
        query_words = set(query.lower().split())
        title_words = set(paper.title.lower().split())
        overlap = len(query_words & title_words)
        if overlap >= 3:
            score = 7.5
        elif overlap >= 1:
            score = 6.0
    return score, usage


async def _score_consistency(paper: Paper, query: str) -> tuple[float, dict]:
    """一致性 LLM 评分（第三维独立信号）：
    评估论文的结论/方法是否与查询所在领域的主流观点对齐，
    以及论文结论的内部一致性。
    """
    prompt = f"""Evaluate the internal consistency and field-alignment of this paper's claims.

Query domain: {query}

Paper: {paper.title}
Abstract (first 250 chars): {paper.abstract[:250]}

Scoring criteria:
- 8-10: Conclusions are well-supported, method clearly explained, aligns with mainstream views
- 5-7:  Generally consistent, minor gaps in method/result narrative
- 1-4:  Internal contradictions, weak support for claims, or contradicts mainstream view

Respond with JSON only:
{{"consistency": <number 0-10>, "reason": "<one sentence>"}}"""

    text, usage = await call_llm(prompt, task_type="fast_score", max_tokens=80, json_mode=True)
    data = _extract_json_object(text)
    if data and "consistency" in data:
        try:
            score = float(data["consistency"])
            score = max(0.0, min(10.0, score))
        except Exception:
            score = 6.0
    else:
        # 兜底 mock：基于年份+venue 做粗略估计
        # 老论文（≥ 5 年）通常方法论已成共识，得分略高
        # 顶会论文通常叙述规范，得分略高
        score = 6.0
        if paper.year and paper.year < 2018:
            score = 7.0
        if paper.venue in ("NeurIPS", "ICML", "ICLR", "Nature", "Science"):
            score = min(8.0, score + 0.5)
    return score, usage


async def rank_node(state: SearchState) -> SearchState:
    """三维评分：相关性(LLM) × 权威性(规则+venue) × 一致性(LLM)。"""

    papers_dicts = state.get("expanded_papers") or state.get("raw_papers") or []
    papers: list[Paper] = []
    for d in papers_dicts:
        try:
            # BUG-004 修复：使用 from_dict 替代 Paper(**d)
            papers.append(Paper.from_dict(d))
        except Exception as e:
            logger.warning(f"[rank_node] Paper deserialize failed: {e}, keys={list(d.keys())[:5]}")
            continue

    query = state["original_query"]

    if not papers:
        return {**state, "ranked_papers": [], "status": "checking_refine"}

    # 限制处理数量控制成本
    papers = papers[:50]

    # 并发评分（限制并发数避免 API 限速）
    semaphore = asyncio.Semaphore(8)

    async def bounded_score_relevance(paper: Paper):
        async with semaphore:
            return await _score_relevance(paper, query)

    async def bounded_score_consistency(paper: Paper):
        async with semaphore:
            return await _score_consistency(paper, query)

    # 并发两个独立维度的 LLM 评分
    rel_results, cons_results = await asyncio.gather(
        asyncio.gather(*[bounded_score_relevance(p) for p in papers]),
        asyncio.gather(*[bounded_score_consistency(p) for p in papers]),
    )

    total_cost = 0.0
    total_tokens = 0

    for paper, (rel, rel_usage), (cons, cons_usage) in zip(papers, rel_results, cons_results):
        paper.relevance_score = rel
        paper.authority_score = _authority_score(paper.citation_count, paper.venue)
        paper.consistency_score = cons
        # 加权：rel 50% + auth 30% + cons 20%
        final = rel * 0.5 + paper.authority_score * 0.3 + cons * 0.2
        # ===== 关键修复：零相关论文降权 =====
        # 当 rel < 4.0（无关键词命中）时，权威性 + 一致性不应让无关论文竞争 Top 名次。
        # 上限设为 rel + 0.5（保证排序时真实相关论文仍在前面）。
        if rel < 4.0:
            final = min(final, rel + 0.5)
        paper.final_score = round(final, 2)
        total_cost += rel_usage.get("cost_usd", 0.0) + cons_usage.get("cost_usd", 0.0)
        total_tokens += (
            rel_usage.get("input_tokens", 0) + rel_usage.get("output_tokens", 0)
            + cons_usage.get("input_tokens", 0) + cons_usage.get("output_tokens", 0)
        )

    papers.sort(key=lambda p: p.final_score, reverse=True)
    ranked = papers[:30]

    top_score = ranked[0].final_score if ranked else 0
    print(
        f"[RankerAgent] Ranked {len(ranked)} papers, top_score={top_score:.2f}, "
        f"cost=${total_cost:.4f}, n_rel_calls={len(rel_results)}, n_cons_calls={len(cons_results)}"
    )

    cost_update = merge_usage_into_state(state, {
        "model": "fast_score_batch_3d",
        "input_tokens": total_tokens,
        "output_tokens": 0,
        "cost_usd": total_cost,
    })

    return {
        **state,
        **cost_update,
        "ranked_papers": [p.to_dict() for p in ranked],
        "status": "checking_refine",
    }
