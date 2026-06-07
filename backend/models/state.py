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

    # M-A 修复 (P0-2 PER_ITER 语义): PER_ITER_BUDGET_CAP_USD 检查的"本轮增量"需要
    # 本字段记录 iter 开始时的累计成本 (snapshot)。
    # 由 search_agent / citation_expander / synthesis_agent / rank_node 入口透传写入
    # (defense-in-depth, 在 cost-free 节点链 search/expand 中也持续刷新, 但因为这两
    # 个节点不调 LLM, snapshot 值 = iter start cost), router 用
    # iter_delta = total_cost_usd - prev_iter_cost_usd 判断单 iter 是否超 $0.3 硬上限。
    prev_iter_cost_usd: Optional[float]

    # 状态机状态
    status: PipelineStatus
    error: Optional[str]

    # LLM provider（用户可选；None → 用 LLM_PROVIDER env 兜底）
    # 由 main.py 在 /search 与 /search/stream 入口解析后注入，agent 节点透传给 call_llm
    provider: Optional[str]

    # 全链路追踪 ID (Round 2 PERF-007):
    #   由 FastAPI middleware 在 HTTP 入口处设置到 contextvars,
    #   在 /search / /search/stream 构造 initial state 时拷贝到 state 字段,
    #   透传到所有 LangGraph 节点, 用于端到端日志关联。
    #   排障时 `grep [<rid>]` 即可还原一次完整调用链。
    request_id: Optional[str]

    # Round 6 M4: query_refiner 跨 retry 复用的 top5 字符串 (R5 S-1 引入, 之前未声明)
    # query_refiner 在每次重试时, 都会用 refine_prompt 再调一次 LLM 把当前
    # ranked_papers 摘要成 1 段 top5 文本, 注入到下一轮 query_decompose 的
    # prompt 里, 让 LLM 知道"上次已经看过这些, 别再返回"。R5 S-1 加了这个
    # 跨 retry cache 机制但没在 TypedDict 显式声明, query_refiner 是用
    # state.get('top5_summary_cache', '') 这种'约定俗成'的弱契约读 — 任何
    # 字段重命名/清理脚本都可能误删。这里显式声明 + Optional[str] 允许 None,
    # 消除'约定俗成'漂移风险 (闭环 R5 S-1)。
    top5_summary_cache: Optional[str]
