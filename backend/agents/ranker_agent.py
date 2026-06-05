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
import asyncio
import logging
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.utils.llm_client import call_llm, merge_usage_into_state
from backend.utils.scrub import scrub_sensitive  # VULN-004
from backend.utils.text_utils import extract_json_object as _extract_json_object

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


async def _score_relevance(paper: Paper, query: str) -> tuple[float, dict]:
    """相关性 LLM 评分（独立信号）。"""
    from backend.utils.sanitize import wrap_user_input, isolation_system_suffix
    safe_query = wrap_user_input(query, tag="user_query")
    # 论文 title/abstract 来自外部 API，是间接注入向量，也要隔离
    safe_paper = wrap_user_input(
        f"Title: {paper.title}\nAbstract: {paper.abstract[:250]}",
        tag="paper",
    )
    prompt = f"""Rate how relevant this paper is to the research query.

{safe_query}

{safe_paper}

Respond with JSON only:
{{"relevance": <number 0-10>, "reason": "<one sentence>"}}
{isolation_system_suffix()}"""

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
    from backend.utils.sanitize import wrap_user_input, isolation_system_suffix
    safe_query = wrap_user_input(query, tag="user_query")
    safe_paper = wrap_user_input(
        f"Title: {paper.title}\nAbstract: {paper.abstract[:250]}",
        tag="paper",
    )
    prompt = f"""Evaluate the internal consistency and field-alignment of this paper's claims.

{safe_query}

{safe_paper}

Scoring criteria:
- 8-10: Conclusions are well-supported, method clearly explained, aligns with mainstream views
- 5-7:  Generally consistent, minor gaps in method/result narrative
- 1-4:  Internal contradictions, weak support for claims, or contradicts mainstream view

Respond with JSON only:
{{"consistency": <number 0-10>, "reason": "<one sentence>"}}
{isolation_system_suffix()}"""

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


async def _score_relevance_batch(papers: list[Paper], query: str) -> tuple[list[float], dict]:
    """Batch relevance scoring: 1 LLM call for up to 10 papers. Returns list of 0-10 scores."""
    from backend.utils.sanitize import wrap_user_input, isolation_system_suffix
    safe_query = wrap_user_input(query, tag="user_query")

    papers_text = "\n\n".join([
        f"[{i+1}] Title: {p.title}\nAbstract: {p.abstract[:200]}"
        for i, p in enumerate(papers)
    ])
    safe_papers = wrap_user_input(papers_text, tag="paper_list")

    prompt = f"""Rate how relevant each of these papers is to the research query.
{isolation_system_suffix()}

{safe_query}

{safe_papers}

Respond with JSON only, mapping paper index to a 0-10 relevance score:
{{
  "scores": {{
    "1": <relevance 0-10>,
    "2": <relevance 0-10>,
    ...
  }}
}}"""
    text, usage = await call_llm(prompt, task_type="fast_score", max_tokens=400, json_mode=True)
    data = _extract_json_object(text)
    scores: list[float] = []
    if data and "scores" in data and isinstance(data["scores"], dict):
        raw = data["scores"]
        for i in range(1, len(papers) + 1):
            try:
                s = float(raw.get(str(i), raw.get(i, 5.0)))
                scores.append(max(0.0, min(10.0, s)))
            except (ValueError, TypeError):
                scores.append(5.0)
    else:
        # 兜底：标题关键词重合度
        query_words = set(query.lower().split())
        for p in papers:
            title_words = set(p.title.lower().split())
            overlap = len(query_words & title_words)
            if overlap >= 3:
                scores.append(7.5)
            elif overlap >= 1:
                scores.append(6.0)
            else:
                scores.append(5.0)
    return scores, usage


async def _score_consistency_batch(papers: list[Paper], query: str) -> tuple[list[float], dict]:
    """Batch consistency scoring: 1 LLM call for up to 10 papers. Returns list of 0-10 scores."""
    from backend.utils.sanitize import wrap_user_input, isolation_system_suffix
    safe_query = wrap_user_input(query, tag="user_query")

    papers_text = "\n\n".join([
        f"[{i+1}] Title: {p.title}\nAbstract: {p.abstract[:200]}"
        for i, p in enumerate(papers)
    ])
    safe_papers = wrap_user_input(papers_text, tag="paper_list")

    prompt = f"""Evaluate the internal consistency and field-alignment of these papers' claims.
{isolation_system_suffix()}

{safe_query}

{safe_papers}

For each paper, score 0-10:
- 8-10: Conclusions well-supported, method clear, aligns with mainstream views
- 5-7:  Generally consistent, minor gaps
- 1-4:  Internal contradictions or weak support

Respond with JSON only:
{{
  "scores": {{
    "1": <consistency 0-10>,
    "2": <consistency 0-10>,
    ...
  }}
}}"""
    text, usage = await call_llm(prompt, task_type="fast_score", max_tokens=400, json_mode=True)
    data = _extract_json_object(text)
    scores: list[float] = []
    if data and "scores" in data and isinstance(data["scores"], dict):
        raw = data["scores"]
        for i in range(1, len(papers) + 1):
            try:
                s = float(raw.get(str(i), raw.get(i, 6.0)))
                scores.append(max(0.0, min(10.0, s)))
            except (ValueError, TypeError):
                scores.append(6.0)
    else:
        # 兜底 mock
        for p in papers:
            s = 6.0
            if p.year and p.year < 2018:
                s = 7.0
            if p.venue in ("NeurIPS", "ICML", "ICLR", "Nature", "Science"):
                s = min(8.0, s + 0.5)
            scores.append(s)
    return scores, usage


async def rank_node(state: SearchState) -> SearchState:
    """三维评分：相关性(LLM) × 权威性(规则+venue) × 一致性(LLM)。"""

    papers_dicts = state.get("expanded_papers") or state.get("raw_papers") or []
    papers: list[Paper] = []
    for d in papers_dicts:
        try:
            # BUG-004 修复：使用 from_dict 替代 Paper(**d)
            papers.append(Paper.from_dict(d))
        except Exception as e:
            logger.warning(f"[rank_node] Paper deserialize failed: {scrub_sensitive(str(e))}, keys={list(d.keys())[:5]}")
            continue

    query = state["original_query"]

    if not papers:
        return {**state, "ranked_papers": [], "status": "checking_refine"}

    # 限制处理数量控制成本
    papers = papers[:50]

    # ===== PERF-003 修复：批量化 LLM 评分 =====
    # 过滤低权威论文（c < 3），减少不必要的 LLM 开销
    papers_filtered = [p for p in papers if p.citation_count >= 3]
    # 限制 35 篇上限
    papers_filtered = papers_filtered[:35]
    if not papers_filtered:
        papers_filtered = papers  # 兜底：全空时不丢论文

    # 分批（每批 10 篇）
    BATCH_SIZE = 10
    batches = [papers_filtered[i:i+BATCH_SIZE] for i in range(0, len(papers_filtered), BATCH_SIZE)]

    # 并发跑两维度的所有 batch（用 semaphore 限流）
    semaphore = asyncio.Semaphore(3)

    async def _rel_batch(batch):
        async with semaphore:
            return await _score_relevance_batch(batch, query)

    async def _cons_batch(batch):
        async with semaphore:
            return await _score_consistency_batch(batch, query)

    rel_batches, cons_batches = await asyncio.gather(
        asyncio.gather(*[_rel_batch(b) for b in batches]),
        asyncio.gather(*[_cons_batch(b) for b in batches]),
    )

    # 展平
    rel_results: list[float] = []
    cons_results: list[float] = []
    total_cost = 0.0
    total_tokens = 0
    for scores, usage in rel_batches:
        rel_results.extend(scores)
        total_cost += usage.get("cost_usd", 0.0)
        total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    for scores, usage in cons_batches:
        cons_results.extend(scores)
        total_cost += usage.get("cost_usd", 0.0)
        total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

    # 给每篇论文写分
    for paper, rel, cons in zip(papers_filtered, rel_results, cons_results):
        paper.relevance_score = rel
        paper.authority_score = _authority_score(paper.citation_count, paper.venue)
        paper.consistency_score = cons
        final = rel * 0.5 + paper.authority_score * 0.3 + cons * 0.2
        if rel < 4.0:
            final = min(final, rel + 0.5)
        paper.final_score = round(final, 2)

    # 把被过滤掉（c < 3）的论文追加在尾部，标 0 分
    seen_ids = {p.paper_id for p in papers_filtered}
    for p in papers:
        if p.paper_id not in seen_ids:
            p.relevance_score = 0.0
            p.authority_score = _authority_score(p.citation_count, p.venue)
            p.consistency_score = 0.0
            p.final_score = 0.0

    papers.sort(key=lambda p: p.final_score, reverse=True)
    ranked = papers[:30]

    top_score = ranked[0].final_score if ranked else 0
    print(
        f"[RankerAgent] Ranked {len(ranked)} papers, top_score={top_score:.2f}, "
        f"cost=${total_cost:.4f}, n_batches_rel={len(rel_batches)}, n_batches_cons={len(cons_batches)}"
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
