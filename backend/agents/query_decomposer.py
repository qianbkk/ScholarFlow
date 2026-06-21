"""
节点 ① — 查询理解与分解
将用户原始查询拆解为 4-5 个英文子查询，供后续多源并行搜索。
"""
import asyncio

from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state
from backend.utils.sanitize import wrap_user_input, isolation_system_suffix  # VULN-001 Layer 1
from backend.utils.text_utils import extract_json_object as _extract_json_object
# R10.5.47 (P1 LLM 输出韧性): Pydantic v2 schema 替换脆弱的 dict.get + isinstance
from backend.agents._schemas import DecomposeOutput, ConstraintsModel, parse_with_retry_async
import logging

logger = logging.getLogger(__name__)


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

# R10.5.15 (P1-D): 5 类 query_type 各自 sub_queries 数量上限.
# 简单查询用少量 (节省 SS/OA 配额 + 减少噪声), 综述查询用多量 (覆盖度优先).
# 跟 prompt 里"Number of sub_queries should match query_type"对齐.
_QUERY_TYPE_LIMITS: dict[str, int] = {
    "simple": 2,      # 单一技术点
    "method": 4,      # 找特定方法
    "comparison": 5,  # 对比型
    "latest": 4,      # 最新进展
    "survey": 6,      # 综述全貌
    "default": 5,     # LLM 没说 / 兜底
}


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


def _sanitize_str_list(raw: object, *, cap: int = 8) -> list[str] | None:
    """R10.5.16 (/simplify 抽): 规范化一个 str list 字段.

    接受 list[str], 去除空白, cap 限长. 失败 (None / 非 list / 含非 str 元素) 返 None.
    用于 query_decomposer 的 venues / methods / datasets 3 维约束清洗.
    """
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        return None
    return [v.strip() for v in raw if v.strip()][:cap]


def _sanitize_constraints(raw: object) -> dict:
    """把 LLM/兜底输出规范化成 constraints dict, 字段全 None 也接受.
    不抛错, 失败时返回全部 None 的占位.

    R10.5.16 (/simplify 合并): 3 段 copy-paste (venues/methods/datasets) 改用
    _sanitize_str_list helper; year_range 单算 (类型 + 范围校验不一样).
    """
    out = {"venues": None, "year_range": None, "methods": None, "datasets": None}
    if not isinstance(raw, dict):
        return out
    out["venues"] = _sanitize_str_list(raw.get("venues"))
    out["methods"] = _sanitize_str_list(raw.get("methods"))
    out["datasets"] = _sanitize_str_list(raw.get("datasets"))
    yr = raw.get("year_range")
    if isinstance(yr, list) and len(yr) == 2:
        try:
            lo, hi = int(yr[0]), int(yr[1])
            if 1900 <= lo <= 2100 and 1900 <= hi <= 2100 and lo <= hi:
                out["year_range"] = [lo, hi]
        except (TypeError, ValueError):
            pass
    return out


async def query_decompose_node(state: SearchState) -> SearchState:
    """将用户原始查询分解为多个英文子查询。"""

    # R10.5.53 (P1 UI 反馈): 节点级思考日志初始化.
    # 各 LLM 节点 (query_decompose / query_refiner / rank / synthesize /
    # critic) 把"思考步骤" append 到 thinking_log[node_name],
    # search.py SSE 在 node_chain_end 时 emit node_thinking 事件推前端.
    thinking = dict(state.get("thinking_log") or {})
    decompose_log: list[str] = []

    def _step(msg: str) -> None:
        decompose_log.append(msg)
        logger.info(f"[query_decompose.thinking] {msg}")

    _step(f"📥 收到原始查询: {state['original_query'][:60]!r}")
    _step("🔍 分析查询意图: 判断 query_type (simple/survey/method/comparison/latest)")

    # ===== 纵深防御 (VULN-001 Layer 1) =====
    # 这是首个 LLM 调用节点：用户原始查询直接拼入 prompt，必须隔离。
    safe_query = wrap_user_input(state['original_query'], tag="user_query")

    prompt = f"""Analyze this research query and decompose it into focused sub-queries.

{safe_query}

Output JSON format:
{{
    "analysis": "Brief analysis of research intent in Chinese (1-2 sentences)",
    "query_type": "simple | survey | method | comparison | latest",
    "sub_queries": [
        "sub-query 1 (English, focus on core topic)",
        "sub-query 2 (English, focus on methods)",
        "sub-query 3 (English, focus on applications)"
    ],
    "key_terms": ["term1", "term2", "term3"],
    "constraints": {{
        "venues": ["NeurIPS", "Nature"],
        "year_range": [2020, 2024],
        "methods": ["transformer", "RL"],
        "datasets": ["ImageNet", "GLUE"]
    }}
}}

query_type 选择规则 (P1-D 自适应分解, R10.5.15):
  - "simple"    : 单一技术点, 1-2 个 sub_queries 够. e.g. "transformer self-attention"
  - "survey"    : 综述型 (想了解领域全貌), 5-6 个 sub_queries. e.g. "graph neural network overview"
  - "method"    : 找特定方法, 3-4 sub_queries. e.g. "AlphaFold protein structure"
  - "comparison": 对比型, 4-5 sub_queries (各对比维度). e.g. "BERT vs GPT vs RoBERTa"
  - "latest"    : 找最新进展, 3-4 sub_queries (偏 recent). e.g. "RLHF alignment 2024"

Rules:
- All sub-queries MUST be in English (academic databases are English-dominant)
- Each sub-query: 3-8 words, specific enough for academic search
- Cover different angles, avoid repetition
- Number of sub_queries should match query_type: simple=1-2, method=3-4, comparison=4-5, latest=3-4, survey=5-6
- If original query is Chinese, translate to academic English
- Extract structured constraints ONLY if the user query explicitly mentions them:
    * venues: e.g. "NeurIPS", "Nature", "CVPR" (publication venue constraints)
    * year_range: [lo, hi] only if query has explicit year(s), e.g. "since 2020", "2022年后"
    * methods: named algorithms/models/methods, e.g. "transformer", "diffusion"
    * datasets: named datasets, e.g. "ImageNet", "GLUE", "MIMIC-III"
- If a constraint is not explicitly mentioned, set that field to null (do not guess)"""

    # R10.5.51 (/simplify): 抽到 _schemas.parse_with_retry_async, ~45 行 → ~10 行.
    # 之前这里内联 Pydantic 校验 + 1 次 retry + merge_usage (ranker 一样,
    # 两份 ~70 行重复, 且 ranker 的 merge_usage 是死代码 bug).
    _step(f"🧠 调用 LLM 抽取 query_type + sub_queries + 4 维约束 "
          f"(system prompt {len(SYSTEM + isolation_system_suffix())} chars, "
          f"max_tokens=500, task_type=complex_reason)")
    sub_queries: list[str] = []
    parsed_obj, usage = await parse_with_retry_async(
        call_llm=call_llm,
        prompt=prompt,
        schema=DecomposeOutput,
        system=SYSTEM + isolation_system_suffix(),
        max_tokens=500,
        task_type="complex_reason",
        provider=state.get("provider"),
        timeout=30.0,
        retry_suffix=(
            "⚠️ 上一轮输出 JSON 解析失败, 必须输出**严格符合 schema 的 JSON**, "
            "不能含 markdown 围栏, 不能含额外说明文字. 仅输出 JSON 对象."
        ),
        log_tag="query_decompose",
        base_usage=None,
    )

    # 解析成功 → 拿 query_type + sub_queries; 解析失败 → R10.5.59b: 严格报错
    if parsed_obj is not None:
        query_type = parsed_obj.query_type
        if query_type not in _QUERY_TYPE_LIMITS:
            query_type = "default"
        max_subs = _QUERY_TYPE_LIMITS[query_type]
        sub_queries = parsed_obj.sub_queries[:max_subs]
        # R10.5.53: 思考日志记录 LLM 输出概要
        _step(f"✅ LLM 解析成功: query_type={query_type}, "
              f"生成 {len(sub_queries)} 个 sub_queries")
        for i, sq in enumerate(sub_queries, 1):
            _step(f"   {i}. {sq}")
        # 把 Pydantic 解析出的 constraints 字段转回 dict 格式 (下游代码用 dict 访问)
        raw_constraints = (
            parsed_obj.constraints.model_dump(exclude_none=True)
            if parsed_obj.constraints is not None
            else None
        )
        if raw_constraints:
            _step(f"📋 抽取约束: venues={raw_constraints.get('venues')}, "
                  f"year_range={raw_constraints.get('year_range')}, "
                  f"methods={raw_constraints.get('methods')}, "
                  f"datasets={raw_constraints.get('datasets')}")
    else:
        # R10.5.59b: 严格 LLM 模式 — LLM 解析失败时禁止走 _fallback_decompose
        # 离线兜底分解 (避免在 LLM 模式下混用本地 mock 数据).
        # LLM 失败 = 立即报错, 让用户知道上游 LLM 服务有问题.
        runtime_mode = state.get("runtime_mode") or "llm"
        if runtime_mode == "llm":
            _step("❌ LLM 解析失败 (2 次重试后仍坏), LLM 模式下禁止离线兜底")
            raise RuntimeError(
                "query_decompose: LLM 解析失败, 2 次重试后仍坏. "
                "LLM 模式 (runtime_mode=llm) 禁止离线兜底分解. "
                "请检查 LLM provider 配置 / 网络 / 预算后重试."
            )
        # local 模式允许离线兜底 (用于离线演示)
        query_type = "default"
        max_subs = _QUERY_TYPE_LIMITS[query_type]
        raw_constraints = None
        _step("⚠️ LLM 解析失败 (2 次重试后仍坏), local 模式走离线兜底分解")
        sub_queries = _fallback_decompose(state["original_query"])

    if not sub_queries:
        # R10.5.59b: local 模式才允许无 sub_queries 兜底, llm 模式已经在上面 raise 了.
        sub_queries = _fallback_decompose(state["original_query"])
    # 限制 sub_queries 数量 — 按 query_type 自适应 (P1-D: 简单查询不浪费 API 配额)
    sub_queries = sub_queries[:max_subs]
    if not sub_queries:
        sub_queries = [state["original_query"]]

    # R10.5.14 (P0-A): 抽结构化约束. LLM 输出优先, 兜底走正则.
    constraints = _sanitize_constraints(raw_constraints)
    fallback_c = _fallback_constraints(state["original_query"])
    # 兜底补 LLM 没抽到的字段 (e.g. LLM 没识别 venue 缩写, 但正则识别了)
    for key, fb_val in fallback_c.items():
        if not constraints.get(key) and fb_val:
            constraints[key] = fb_val
    # R10.5.15 (P1-D): 把 query_type 也塞进 constraints (跟前 4 维并列, 不破坏
    # 现有约束 schema, 下游 search/synth 节点可读)
    constraints["query_type"] = query_type

    cost_update = merge_usage_into_state(state, usage or {})

    # R10.5.53: 把本节点的思考日志写回 state, search.py SSE 推前端
    _step(f"🚀 进入下一节点: search (双源检索) — "
          f"{len(sub_queries)} sub_queries 准备检索")
    thinking["query_decompose"] = decompose_log

    return {
        **state,
        **cost_update,
        "sub_queries": sub_queries,
        "constraints": constraints,
        "thinking_log": thinking,
        "status": "searching",
    }
