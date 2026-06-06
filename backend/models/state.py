"""LangGraph 状态机状态定义。"""
from typing import TypedDict, Optional, Literal


# 流水线状态机中所有合法 `status` 取值。
# 工作流节点按顺序推进 status；如果某个 status 字符串不在这里，类型检查会报错，
# 防止拼写错误（如 "synthesise" vs "synthesizing"）扩散到整条流水线。
PipelineStatus = Literal[
    "decomposing",
    "searching",
    "expanding",
    "ranking",
    "checking_refine",
    "synthesizing",
    "building_graph",
    "done",
    "error",
]


class SearchState(TypedDict):
    # 输入
    original_query: str

    # 处理过程（每步更新）
    sub_queries: list[str]
    raw_papers: list[dict]
    expanded_papers: list[dict]
    ranked_papers: list[dict]

    # 输出
    report: str
    citation_graph: dict  # {"nodes": [...], "links": [...]}

    # 迭代控制
    iteration: int
    max_iterations: int
    # 已做过引文扩展的 seed paper_id（跨迭代去重，避免重复调 get_references）
    expanded_paper_ids: list[str]

    # 成本追踪
    total_tokens_used: int
    total_cost_usd: float
    budget_limit_usd: float
    model_usage: dict  # {"model-name": {"tokens": int, "cost": float}}

    # 状态机状态
    status: PipelineStatus
    error: Optional[str]
