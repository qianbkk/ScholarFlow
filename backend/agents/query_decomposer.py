"""
节点 ① — 查询理解与分解
将用户原始查询拆解为 4-5 个英文子查询，供后续多源并行搜索。
"""
import json
import re
from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state


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


def _extract_json_object(text: str) -> dict | None:
    """从 LLM 文本中提取第一个 JSON 对象。"""
    if not text:
        return None
    # 直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 抽取代码块中的 JSON
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


async def query_decompose_node(state: SearchState) -> SearchState:
    """将用户原始查询分解为多个英文子查询。"""

    prompt = f"""Analyze this research query and decompose it into 4-5 focused sub-queries.

Original query: {state['original_query']}

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

    text, usage = await call_llm(
        prompt,
        task_type="complex_reason",
        system=SYSTEM,
        max_tokens=800,
        json_mode=True,
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
