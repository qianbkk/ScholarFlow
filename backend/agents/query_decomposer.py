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


# R10.5.14 (P0-A): 离线正则抽 4 维约束, 跟 LLM 抽取互补.
# LLM 失败时仍能给 search_agent 一个粗粒度约束集 (至少 1-2 个常见 venue/year
# 能 catch 住), 避免完全没约束. 正则只匹配显式信号, 不做语义推断, 误抽比漏抽
# 更糟糕 (会把用户原本不限 venue 的查询强行收窄).
import re as _re

_VENUE_HINTS = (
    "NeurIPS", "ICML", "ICLR", "AAAI", "IJCAI", "KDD", "ACL", "EMNLP",
    "NAACL", "CVPR", "ICCV", "ECCV", "MICCAI", "SIGGRAPH", "CHI", "UIST",
    "Nature", "Science", "Cell", "Lancet", "JAMA", "NEJM",
    "JMLR", "TPAMI", "ICRA", "IROS", "RSS",
)

_YEAR_RE = _re.compile(r"\b(?:19|20)\d{2}\b")


def _fallback_constraints(query: str) -> dict:
    """从 query 文本里粗抽 venues / year_range / methods / datasets.
    抽不到 → 对应字段 None. 返回 dict 形态跟 LLM 输出一致."""
    q = query or ""
    venues = sorted({v for v in _VENUE_HINTS if v in q})
    years = [int(y) for y in _YEAR_RE.findall(q)]
    year_range = None
    if years:
        # 单年/多年: 给定最小-最大, 若同一年出现多次取同值
        lo, hi = min(years), max(years)
        year_range = [lo, hi] if lo != hi else [lo, lo]
    # methods / datasets 离线抽成本高(需要词典), 留 None 让 LLM 来抽
    return {
        "venues": venues or None,
        "year_range": year_range,
        "methods": None,
        "datasets": None,
    }


def _sanitize_constraints(raw: object) -> dict:
    """把 LLM/兜底输出规范化成 constraints dict, 字段全 None 也接受.
    不抛错, 失败时返回全部 None 的占位."""
    out = {"venues": None, "year_range": None, "methods": None, "datasets": None}
    if not isinstance(raw, dict):
        return out
    venues = raw.get("venues")
    if isinstance(venues, list) and all(isinstance(v, str) for v in venues):
        out["venues"] = [v.strip() for v in venues if v.strip()][:8]
    yr = raw.get("year_range")
    if isinstance(yr, list) and len(yr) == 2:
        try:
            lo, hi = int(yr[0]), int(yr[1])
            if 1900 <= lo <= 2100 and 1900 <= hi <= 2100 and lo <= hi:
                out["year_range"] = [lo, hi]
        except (TypeError, ValueError):
            pass
    methods = raw.get("methods")
    if isinstance(methods, list) and all(isinstance(m, str) for m in methods):
        out["methods"] = [m.strip() for m in methods if m.strip()][:8]
    datasets = raw.get("datasets")
    if isinstance(datasets, list) and all(isinstance(d, str) for d in datasets):
        out["datasets"] = [d.strip() for d in datasets if d.strip()][:8]
    return out


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
    "key_terms": ["term1", "term2", "term3"],
    "constraints": {{
        "venues": ["NeurIPS", "Nature"],
        "year_range": [2020, 2024],
        "methods": ["transformer", "RL"],
        "datasets": ["ImageNet", "GLUE"]
    }}
}}

Rules:
- All sub-queries MUST be in English (academic databases are English-dominant)
- Each sub-query: 3-8 words, specific enough for academic search
- Cover different angles, avoid repetition
- If original query is Chinese, translate to academic English
- Extract structured constraints ONLY if the user query explicitly mentions them:
    * venues: e.g. "NeurIPS", "Nature", "CVPR" (publication venue constraints)
    * year_range: [lo, hi] only if query has explicit year(s), e.g. "since 2020", "2022年后"
    * methods: named algorithms/models/methods, e.g. "transformer", "diffusion"
    * datasets: named datasets, e.g. "ImageNet", "GLUE", "MIMIC-III"
- If a constraint is not explicitly mentioned, set that field to null (do not guess)"""

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

    # R10.5.14 (P0-A): 抽结构化约束. LLM 输出优先, 兜底走正则.
    constraints = _sanitize_constraints(parsed.get("constraints")) if parsed else _sanitize_constraints(None)
    fallback_c = _fallback_constraints(state["original_query"])
    # 兜底补 LLM 没抽到的字段 (e.g. LLM 没识别 venue 缩写, 但正则识别了)
    for key, fb_val in fallback_c.items():
        if not constraints.get(key) and fb_val:
            constraints[key] = fb_val

    cost_update = merge_usage_into_state(state, usage)

    return {
        **state,
        **cost_update,
        "sub_queries": sub_queries,
        "constraints": constraints,
        "status": "searching",
    }
