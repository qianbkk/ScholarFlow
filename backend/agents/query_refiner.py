"""
节点 ⑤ — 自适应查询优化
分析当前结果不足，生成补充查询词。
"""
import logging
from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state
from backend.utils.sanitize import wrap_user_input, isolation_system_suffix  # VULN-001 Layer 1
from backend.utils.text_utils import extract_json_object as _extract_json_object

logger = logging.getLogger(__name__)


async def query_refine_node(state: SearchState) -> SearchState:
    """分析当前结果的不足，生成补充查询词。"""

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

    text, usage = await call_llm(
        prompt,
        task_type="refine_strategy",
        system=isolation_system_suffix(),
        max_tokens=400,
        json_mode=True,
        provider=state.get("provider"),
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
