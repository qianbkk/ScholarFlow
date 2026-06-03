"""
节点 ④ — 三维质检排序
- 相关性 (LLM, fast model)
- 权威性 (基于引用数的规则)
- 一致性 (暂时 = (相关性 + 权威性) / 2 估算)
- final = 0.5*rel + 0.3*auth + 0.2*cons
"""
import json
import asyncio
import re
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.utils.llm_client import call_llm, merge_usage_into_state


def _authority_score(citation_count: int) -> float:
    """基于引用数计算权威性（不消耗 token）。"""
    thresholds = [
        (1000, 10.0), (500, 9.0), (200, 8.0), (100, 7.5),
        (50, 7.0), (20, 6.0), (10, 5.0), (5, 4.0), (1, 3.0),
    ]
    for threshold, score in thresholds:
        if citation_count >= threshold:
            return score
    return 2.0


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
    """单篇论文相关性评分。"""
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


async def rank_node(state: SearchState) -> SearchState:
    """三维评分：相关性(LLM) × 权威性(规则) × 一致性(估算)。"""

    papers_dicts = state.get("expanded_papers") or state.get("raw_papers") or []
    papers: list[Paper] = []
    for d in papers_dicts:
        try:
            papers.append(Paper(**d))
        except Exception:
            continue

    query = state["original_query"]

    if not papers:
        return {**state, "ranked_papers": [], "status": "checking_refine"}

    # 限制处理数量控制成本
    papers = papers[:50]

    # 并发评分（限制并发数避免 API 限速）
    semaphore = asyncio.Semaphore(8)

    async def bounded_score(paper: Paper):
        async with semaphore:
            return await _score_relevance(paper, query)

    score_results = await asyncio.gather(*[bounded_score(p) for p in papers])

    total_cost = 0.0
    total_tokens = 0

    for paper, (rel, usage) in zip(papers, score_results):
        paper.relevance_score = rel
        paper.authority_score = _authority_score(paper.citation_count)
        # 一致性：暂时用 (rel + auth) / 2 作为估算
        paper.consistency_score = round((rel + paper.authority_score) / 2, 1)
        # 加权
        paper.final_score = round(
            rel * 0.5 + paper.authority_score * 0.3 + paper.consistency_score * 0.2, 2
        )
        total_cost += usage.get("cost_usd", 0.0)
        total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

    papers.sort(key=lambda p: p.final_score, reverse=True)
    ranked = papers[:30]

    top_score = ranked[0].final_score if ranked else 0
    print(f"[RankerAgent] Ranked {len(ranked)} papers, top_score={top_score:.2f}, cost=${total_cost:.4f}")

    cost_update = merge_usage_into_state(state, {
        "model": "fast_score_batch",
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
