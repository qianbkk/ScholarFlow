"""
节点 ① — 查询理解与分解
将用户原始查询拆解为 4-5 个英文子查询，供后续多源并行搜索。
"""
import asyncio

from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state
from backend.utils.sanitize import wrap_user_input, isolation_system_suffix  # VULN-001 Layer 1
from backend.utils.text_utils import extract_json_object as _extract_json_object


SYSTEM = (
    "You are an expert academic librarian. "
    "Your job is to decompose complex research queries into precise sub-queries "
    "for searching academic databases like Semantic Scholar and OpenAlex."
)


# 离线兜底：基于关键词拆分
def _fallback_decompose(query: str) -> list[str]:
    """LLM 不可用时的简单拆分兜底。"""
    base = query.strip()
    sub_queries = [
        base,
        f"{base} survey",
        f"{base} recent advances",
        f"{base} benchmark",
        f"{base} method comparison",
    ]
    # 去重保序
    seen = set()
    result = []
    for q in sub_queries:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            result.append(q)
    return result[:5]


async def query_decompose_node(state: SearchState) -> SearchState:
    """将用户原始查询分解为多个英文子查询。"""

    # ===== 纵深防御 (VULN-001 Layer 1) =====
    # 这是首个 LLM 调用节点：用户原始查询直接拼入 prompt，必须隔离。
    safe_query = wrap_user_input(state['original_query'], tag="user_query")

    prompt = f"""Analyze this research query and decompose it into 4-5 focused sub-queries.

{safe_query}

Output JSON format:
{{
    "analysis": "Brief analysis of research intent in Chinese (1-2 sentences)",
    "sub_queries": [
        "sub-query 1 (English, focus on core topic)",
        "sub-query 2 (English, focus on methods)",
        "sub-query 3 (English, focus on applications)",
        "sub-query 4 (English, related technology/context)",
        "sub-query 5 (English, broader background)"
    ],
    "key_terms": ["term1", "term2", "term3"]
}}

Rules:
- All sub-queries MUST be in English (academic databases are English-dominant)
- Each sub-query: 3-8 words, specific enough for academic search
- Cover different angles, avoid repetition
- If original query is Chinese, translate to academic English"""

    # R10.5 Fix-P: 节点级 30s 上限, 防 query_decompose hang 住整个 pipeline.
    # max_tokens=500 + 简单 prompt 实测 5-10s, 30s 留 3x buffer.
    text, usage = await asyncio.wait_for(
        call_llm(
            prompt,
            task_type="complex_reason",
            system=SYSTEM + isolation_system_suffix(),
            max_tokens=500,
            json_mode=True,
            provider=state.get("provider"),
        ),
        timeout=30.0,
    )

    sub_queries: list[str] = []
    parsed = _extract_json_object(text)
    if parsed:
        for q in parsed.get("sub_queries", []):
            if isinstance(q, str):
                q = q.strip()
                if len(q) > 3:
                    sub_queries.append(q)
    if not sub_queries:
        # 兜底：原始查询 + 派生变体
        sub_queries = _fallback_decompose(state["original_query"])
    # 限制最多 5 个
    sub_queries = sub_queries[:5]
    if not sub_queries:
        sub_queries = [state["original_query"]]

    cost_update = merge_usage_into_state(state, usage)

    return {
        **state,
        **cost_update,
        "sub_queries": sub_queries,
        "status": "searching",
    }
