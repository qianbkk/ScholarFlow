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
# R10.5.46: prune_state 抽到 _state_utils.py 共享, search_node 入口也调.
from backend.agents._state_utils import prune_state
from backend.agents._step_helper import _step  # R10.5.55

logger = logging.getLogger(__name__)


async def query_refine_node(state: SearchState) -> SearchState:
    """分析当前结果的不足，生成补充查询词。"""

    # R10.5.22 + R10.5.46: 入口先裁剪 state, 防止本 iter 读到大膨胀 list
    state = prune_state(state)
    _step(state, "refine", f"🔍 分析 top 5 gap · iter={state.get('iteration', 0)}")

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

    # R10.5.59: LLM 模式放宽阈值 — 若本轮 ranked < paper_min 且未放宽,
    # 把 score_threshold 从 8.0 降到 7.0, 标记 score_relaxed=True.
    # 下一轮 rank_node 用 7.0 筛选; 再不够宁可降低数量, 绝不 mock fallback.
    runtime_mode = state.get("runtime_mode") or "llm"
    paper_min = int(state.get("paper_min") or 5)
    cur_threshold = float(state.get("score_threshold") or 0.0)
    already_relaxed = bool(state.get("score_relaxed", False))
    ranked_count = len(ranked)
    new_threshold = cur_threshold
    new_relaxed = already_relaxed
    if (
        runtime_mode == "llm"
        and cur_threshold >= 8.0
        and not already_relaxed
        and ranked_count < paper_min
    ):
        new_threshold = 7.0
        new_relaxed = True
        _step(
            state,
            "refine",
            f"📉 放宽阈值 8.0 → 7.0 (本轮 ranked={ranked_count} < paper_min={paper_min})",
        )
        logger.info(
            f"[QueryRefiner] relax score_threshold 8.0 → 7.0 "
            f"(ranked={ranked_count} < paper_min={paper_min})"
        )

    _step(state, "refine", f"🧠 LLM 生成 {len(new_queries)} new sub_queries")
    _step(state, "refine", f"↻ 启动 iteration {iteration + 1}")

    return {
        **state,
        **cost_update,
        "sub_queries": new_queries if new_queries else (state.get("sub_queries") or [state["original_query"]]),
        "iteration": iteration + 1,
        "status": "checking_refine",
        "top5_summary_cache": safe_top5,
        "score_threshold": new_threshold,
        "score_relaxed": new_relaxed,
    }
