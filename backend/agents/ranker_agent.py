"""
节点 ④ — 三维质检排序

三维评分（真正独立）：
- 相关性 Relevance (LLM, fast model)        — 论文与查询的语义相关度
- 权威性 Authority (基于引用数规则 + venue  ) — 学术影响力
- 一致性 Consistency (LLM, fast model)        — 论文结论与领域主流观点的对齐度（独立维度）

final = 0.5*rel + 0.3*auth + 0.2*cons

PERF 优化：相关性 + 一致性 已合并为单次 LLM 调用（_score_papers_combined_batch），
节省约 50% token（原本每篇论文 2 次 LLM 调用，现在 1 次）。

注：早期版本 consistency 是 (rel+auth)/2 估算，存在文档与代码不一致的诚信问题。
本次实现真正调用 LLM 进行一致性评估，并提供 mock 兜底以保证 mock 模式可演示。
"""
import asyncio
import logging
from typing import Optional
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
    # 数据库
    "SIGMOD": 0.25, "VLDB": 0.25,
    # 软件工程
    "FSE": 0.2, "ICSE": 0.2,
    # HCI
    "CHI": 0.2,
    # 语言模型会议 (2024+)
    "COLM": 0.3,
    # WWW 正式名称
    "TheWebConf": 0.2,
    # 图形学
    "SIGGRAPH": 0.3,
    # 理论 CS
    "STOC": 0.3, "FOCS": 0.3,
    # 计算生物学
    "RECOMB": 0.25,
}


def _authority_score(citation_count: int, venue: str = "", year: int = 0) -> float:
    """基于引用数 + venue + 年份 计算权威性（不消耗 token）。

    R10.5 Fix-I + Fix-J (审计 PPP §3.3 + QQQ §3.1):
      旧版无年份因子, 2017 Transformer (95000 引) 9.0 vs 2024 GraphRAG
      (850 引) 6.0 — 系统性偏向老论文. 改用年均引用数 + 新发表加成.

    R10.5 Fix-I (QQQ §3.1): 旧版 rel<4 才压制, 但 mock 兜底 rel=5.0/6.0
      高于阈值, 无关高引论文进 Top 25. 提到 rel<5.5 压制, 兜底论文挡得住.
    """
    from datetime import datetime
    current_year = datetime.now().year
    age = max(1, current_year - year) if year and year > 2000 else 10
    annual_citations = citation_count / age

    # 年均引用数分段 (阈值降以适应新论文)
    annual_thresholds = [
        (300, 9.0), (100, 8.5), (50, 8.0), (20, 7.5),
        (10, 7.0), (5, 6.0), (2, 5.0), (0.5, 4.0),
    ]
    base = 2.0
    for threshold, score in annual_thresholds:
        if annual_citations >= threshold:
            base = score
            break

    # 新发表加成: 不足 2 年但已有 30+ 引用, 影响力正在爆发
    if year and age <= 2 and citation_count >= 30:
        base = min(10.0, base + 0.8)

    bonus = _VENUE_BONUS.get(venue, 0.0)
    return min(10.0, base + bonus)


async def _score_papers_combined_batch(
    papers: list[Paper], query: str, provider: Optional[str] = None,
) -> tuple[list[float], list[float], dict]:
    """Combined batch scoring: 1 LLM call returns BOTH relevance + consistency per paper.

    Returns: (relevance_scores, consistency_scores, usage)
    节省约 50% token：相关性 + 一致性 双维度单次 LLM 调用合并。
    """
    from backend.utils.sanitize import wrap_user_input, isolation_system_suffix
    safe_query = wrap_user_input(query, tag="user_query")

    papers_text = "\n\n".join([
        f"[{i+1}] Title: {p.title}\nAbstract: {p.abstract[:200]}"
        for i, p in enumerate(papers)
    ])
    safe_papers = wrap_user_input(papers_text, tag="paper_list")

    prompt = f"""Rate each paper on TWO dimensions in a single response.

Dimension 1 — relevance (how relevant the paper is to the research query):
- 8-10: Directly addresses the query
- 5-7:  Tangentially related
- 1-4:  Not relevant

Dimension 2 — consistency (internal consistency and field-alignment of claims):
- 8-10: Conclusions well-supported, method clear, aligns with mainstream views
- 5-7:  Generally consistent, minor gaps
- 1-4:  Internal contradictions or weak support
{isolation_system_suffix()}

{safe_query}

{safe_papers}

Respond with JSON only, mapping paper index to BOTH scores:
{{
  "1": {{"relevance": <0-10>, "consistency": <0-10>}},
  "2": {{"relevance": <0-10>, "consistency": <0-10>}},
  ...
}}"""
    # R10.5 Fix-P: 节点级 60s 上限, 防 LLM 评分 hang 住.
    # fast_score 35 篇/批理论上 <10s, 60s 留 6x buffer.
    text, usage = await asyncio.wait_for(
        call_llm(prompt, task_type="fast_score", max_tokens=600, json_mode=True, provider=provider),
        timeout=60.0,
    )
    data = _extract_json_object(text)
    rel_scores: list[float] = []
    cons_scores: list[float] = []
    if isinstance(data, dict):
        for i in range(1, len(papers) + 1):
            entry = data.get(str(i), data.get(i, {}))
            if not isinstance(entry, dict):
                entry = {}
            try:
                r = float(entry.get("relevance", 5.0))
                rel_scores.append(max(0.0, min(10.0, r)))
            except (ValueError, TypeError):
                rel_scores.append(5.0)
            try:
                c = float(entry.get("consistency", 6.0))
                cons_scores.append(max(0.0, min(10.0, c)))
            except (ValueError, TypeError):
                cons_scores.append(6.0)
    else:
        # 兜底：按 query-title 重叠度（与原 batch 行为一致）
        query_words = set(query.lower().split())
        for p in papers:
            title_words = set(p.title.lower().split())
            overlap = len(query_words & title_words)
            if overlap >= 3:
                rel_scores.append(7.5)
            elif overlap >= 1:
                rel_scores.append(6.0)
            else:
                rel_scores.append(5.0)
            c = 6.0
            if p.year and p.year < 2018:
                c = 7.0
            if p.venue in ("NeurIPS", "ICML", "ICLR", "Nature", "Science"):
                c = min(8.0, c + 0.5)
            cons_scores.append(c)
    return rel_scores, cons_scores, usage


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

    # ===== Round 2 PERF-006: 跨迭代复用 relevance/consistency score =====
    # Root cause: refine 迭代会重新调 LLM 给所有论文打分, 即使前一轮已评过
    # (relevance/consistency 已写入 expanded_papers dict 跨迭代保留), 浪费 ~50% LLM token。
    # Fix: 仅对 relevance_score == 0 或 consistency_score == 0 的论文调 LLM,
    #      其余论文直接复用缓存的 final_score / authority / relevance / consistency。
    # Verification: log 报告 scoring N new papers (skipped M already scored);
    #               全部已评时 LLM 调用数为 0 (fast-path), total_cost=$0.0000。
    papers_to_score = [p for p in papers_filtered if p.relevance_score == 0 or p.consistency_score == 0]
    papers_already_scored = [p for p in papers_filtered if p.relevance_score > 0 and p.consistency_score > 0]

    if not papers_to_score:
        logger.info(
            f"[rank_node] all {len(papers_filtered)} papers already scored, skip LLM "
            f"(Round 2 PERF-006 cross-iteration cache hit)"
        )
    else:
        logger.info(
            f"[rank_node] scoring {len(papers_to_score)} new papers "
            f"(skipped {len(papers_already_scored)} already scored, Round 2 PERF-006)"
        )

    # 分批（每批 10 篇）— 只对 papers_to_score 调 LLM; 空列表 = 0 token
    BATCH_SIZE = 10
    batches = [papers_to_score[i:i+BATCH_SIZE] for i in range(0, len(papers_to_score), BATCH_SIZE)]

    # ===== PERF: 合并相关性 + 一致性 单次 LLM 调用（节省 50% token）=====
    # 旧版：每篇论文 × 2 次调用 (relevance + consistency)
    # 新版：每批 × 1 次调用，同时返回两个分数
    semaphore = asyncio.Semaphore(3)
    # 透传用户选择的 LLM provider — 5 个 agent 节点中此处最复杂
    # （需要把 provider 传进 _combined_batch → _score_papers_combined_batch → call_llm）
    rank_provider = state.get("provider")

    async def _combined_batch(batch):
        async with semaphore:
            return await _score_papers_combined_batch(batch, query, provider=rank_provider)

    # H3 修复：gather 必须用 return_exceptions=True
    # 旧实现：单批失败（LLM 429 / JSON parse error）会传播并崩溃整个 ranker 节点，
    # 导致整条流水线 500。对照 search_node:29 / citation_expander:61,65 都已用
    # return_exceptions=True + 后续 isinstance 过滤异常。
    combined_batches = await asyncio.gather(
        *[_combined_batch(b) for b in batches],
        return_exceptions=True,
    )

    # 展平（H3 修复：失败的批次用兜底分数 5.0/6.0，与 _score_papers_combined_batch 内部兜底一致）
    rel_results: list[float] = []
    cons_results: list[float] = []
    total_cost = 0.0
    total_tokens = 0
    for batch, result in zip(batches, combined_batches):
        if isinstance(result, Exception):
            # 单批失败：记录 warning，用兜底分数填平（不污染其他批次的结果）
            logger.warning(
                f"[rank_node] batch scoring failed "
                f"(batch_size={len(batch)}, err={type(result).__name__}: "
                f"{scrub_sensitive(str(result))}); "
                f"using fallback scores 5.0/6.0 for this batch"
            )
            rel_results.extend([5.0] * len(batch))
            cons_results.extend([6.0] * len(batch))
            continue
        rel_scores, cons_scores, usage = result
        rel_results.extend(rel_scores)
        cons_results.extend(cons_scores)
        total_cost += usage.get("cost_usd", 0.0)
        total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

    # 给每篇"本轮新评分"的论文写分
    # 已评过的论文 (papers_already_scored) 保留前一轮写入的
    # relevance / consistency / authority / final_score, 不在本轮重算
    # (Round 2 PERF-006 跨迭代缓存)。
    for paper, rel, cons in zip(papers_to_score, rel_results, cons_results):
        paper.relevance_score = rel
        paper.authority_score = _authority_score(paper.citation_count, paper.venue, paper.year or 0)
        paper.consistency_score = cons
        final = rel * 0.5 + paper.authority_score * 0.3 + cons * 0.2
        # Fix-I R10.5: 阈值 4.0 → 5.5. 旧阈值在 mock 兜底 rel=5.0/6.0 时失效,
        # 无关高引论文(alphafold 类) 拿到 6.4 污染 Top 25. 新阈值压制兜底.
        if rel < 5.5:
            final = min(final, rel * 0.8)
        paper.final_score = round(final, 2)

    # 把被过滤掉（c < 3）的论文追加在尾部，标 0 分
    seen_ids = {p.paper_id for p in papers_filtered}
    for p in papers:
        if p.paper_id not in seen_ids:
            p.relevance_score = 0.0
            p.authority_score = _authority_score(p.citation_count, p.venue, p.year or 0)
            p.consistency_score = 0.0
            p.final_score = 0.0

    papers.sort(key=lambda p: p.final_score, reverse=True)
    # FIX: 统一 ranked 论文数为 25 — 与 synthesis / graph_builder 的 [:25] 截断对齐
    # 旧 [:30] 导致 21-30 论文在 report + graph 中被丢弃（暗物质）。
    ranked = papers[:25]

    top_score = ranked[0].final_score if ranked else 0
    logger.info(
        f"[RankerAgent] Ranked {len(ranked)} papers, top_score={top_score:.2f}, "
        f"cost=${total_cost:.4f}, n_batches_combined={len(combined_batches)}"
    )

    cost_update = merge_usage_into_state(state, {
        "model": "fast_score_batch_3d",
        "input_tokens": total_tokens,
        "output_tokens": 0,
        "cost_usd": total_cost,
    })

    # M-A 修复 (P0-1 状态爆炸): rank_node 之后再无节点读取 raw_papers / expanded_papers,
    # 它们继续随 {**state} 拷贝是浪费 (~125+50 篇 dict, ~300KB/worker × 4 worker × 4 step
    # = ~1.2MB 冗余内存 + GC 压力)。这里显式清零以释放后续 synthesis / graph_builder /
    # cost_tracker 节点的 state 拷贝压力。ranked_papers 保留 (synthesis 读)。
    # M-A 修复 (P0-2 PER_ITER 语义): 记录本次 iter 结束时(rank 入口)的累计成本快照,
    # 供 router 计算"本轮真实增量" (iter_delta = cost_now - prev_iter_cost_usd)。
    # 注: 真正的 iter-START 值由 search_agent 入口写入 (透传 prev_iter_cost 链),
    #     这里再写一次作为 defense-in-depth。
    return {
        **state,
        **cost_update,
        "ranked_papers": [p.to_dict() for p in ranked],
        "raw_papers": [],          # M-A P0-1: 节点②③ 之后已无节点读取, 清零
        "expanded_papers": [],     # M-A P0-1: 同上
        "prev_iter_cost_usd": state.get("total_cost_usd", 0.0),  # M-A P0-2: iter 结束成本快照
        "status": "checking_refine",
    }
