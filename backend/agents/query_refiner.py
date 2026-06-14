"""
节点 ⑤ — 自适应查询优化
分析当前结果不足，生成补充查询词。
"""
import asyncio
import logging
from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state
from backend.utils.sanitize import wrap_user_input, isolation_system_suffix  # VULN-001 Layer 1
from backend.utils.text_utils import extract_json_object as _extract_json_object

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
    """U.txt 审计 #2 修复: 跨迭代 state 裁剪, 防 raw/expanded/ranked 无限累积.

    在 query_refine_node 入口 + 每次 refine 后调一次. 不修改 iteration / status,
    只把 3 个 paper list 截到上限, 减少下游 LLM 拼接 + SSE 序列化成本.
    """
    raw = state.get("raw_papers") or []
    expanded = state.get("expanded_papers") or []
    ranked = state.get("ranked_papers") or []
    new_state = dict(state)
    if len(raw) > RAW_PAPERS_CAP:
        new_state["raw_papers"] = _prune_papers_by_score(raw, RAW_PAPERS_CAP)
    if len(expanded) > EXPANDED_PAPERS_CAP:
        new_state["expanded_papers"] = _prune_papers_by_score(expanded, EXPANDED_PAPERS_CAP)
    if len(ranked) > RANKED_PAPERS_CAP:
        new_state["ranked_papers"] = _prune_papers_by_score(ranked, RANKED_PAPERS_CAP)
    return new_state  # type: ignore[return-value]


async def query_refine_node(state: SearchState) -> SearchState:
    """分析当前结果的不足，生成补充查询词。"""

    # R10.5.22: 入口先裁剪 state, 防止本 iter 读到大膨胀 list
    state = prune_state(state)

    ranked = state.get("ranked_papers") or []
    iteration = state.get("iteration", 0)

    # ===== 纵深防御 (VULN-001 Layer 1) =====
    # 用户原始查询：不可信输入
    safe_query = wrap_user_input(state['original_query'], tag="user_query")
    # 论文标题来自外部 API (Semantic Scholar / OpenAlex)，是间接注入向量
    # 同样用 XML 标签隔离
    # Round 5 S-1: 缓存 top5_summary 字符串, 跨 retry / 循环复用,
    # 避免每次重算 ranked[:5] -> "\n".join(...) -> wrap_user_input。
    if "top5_summary_cache" in state and state["top5_summary_cache"]:
        safe_top5 = state["top5_summary_cache"]
    else:
        top5_summary = "\n".join([
            f"- [{p.get('year','')}] {p.get('title','')} (relevance: {p.get('relevance_score',0):.1f})"
            for p in ranked[:5]
        ])
        safe_top5 = wrap_user_input(top5_summary, tag="paper_list")

    prompt = f"""You're a research strategy expert. Analyze these search results and identify gaps.

{safe_query}
Search iteration: {iteration + 1}

Current top results:
{safe_top5}

What important aspects are MISSING from these results?
Generate 3 NEW search queries to fill the gaps.

JSON output:
{{
    "gap_analysis": "What's missing (in Chinese, 1-2 sentences)",
    "new_sub_queries": [
        "gap-filling query 1 (English)",
        "gap-filling query 2 (English)",
        "gap-filling query 3 (English)"
    ]
}}"""

    # R10.5 Fix-P: 节点级 30s 上限, refine 循环里如果 hang 住会放大成本
    # (max_iter=3 × 30s = 90s 仅 query_refine 就耗尽 endpoint 480s).
    text, usage = await asyncio.wait_for(
        call_llm(
            prompt,
            task_type="refine_strategy",
            system=isolation_system_suffix(),
            max_tokens=400,
            json_mode=True,
            provider=state.get("provider"),
        ),
        timeout=30.0,
    )

    new_queries: list[str] = []
    parsed = _extract_json_object(text)
    if parsed:
        candidates = parsed.get("new_sub_queries", [])
        existing = set(state.get("sub_queries", []))
        for q in candidates:
            if not isinstance(q, str):
                continue
            q = q.strip()
            if q and q not in existing:
                new_queries.append(q)
        new_queries = new_queries[:3]

    cost_update = merge_usage_into_state(state, usage)

    logger.info(f"[QueryRefiner] iter={iteration+1} | new_queries={len(new_queries)}")

    return {
        **state,
        **cost_update,
        "sub_queries": new_queries if new_queries else (state.get("sub_queries") or [state["original_query"]]),
        "iteration": iteration + 1,
        "status": "checking_refine",
        "top5_summary_cache": safe_top5,
    }
