"""LangGraph 状态机状态定义。"""
from typing import TypedDict, Optional


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
    status: str
    error: Optional[str]
