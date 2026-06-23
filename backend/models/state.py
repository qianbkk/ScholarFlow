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

    # R10.5.14: 结构化约束, query_decomposer 从用户 query 里抽 4 维:
    #   venues: ["NeurIPS", "Nature"]   - 发表 venue
    #   year_range: [2020, 2024]        - 时间范围 (可空表示无下/上限)
    #   methods: ["transformer", "RL"]  - 方法论
    #   datasets: ["ImageNet", "GLUE"]  - 数据集
    # 没抽到就 None, search_agent 透传给 SS/OA 做精确过滤。
    # R10.5.15 (P1-D): 加 query_type (simple/survey/method/comparison/latest),
    # 让 search/synthesize 节点可按意图调 sub_queries 数量 / 报告侧重.
    constraints: Optional[dict]

    # R10.5.46 (P1 LangGraph safety net): 连续 0 结果迭代计数器.
    # 防"冷门查询 / 乱码查询"在 refine 循环里死磕 budget 耗尽.
    # 0 结果: streak +1; 有结果: streak = 0.
    # router.should_refine 在 streak >= 2 时强制 synthesize (避免 3 次空迭代).
    empty_result_streak: int

    # R10.5.53 (P1 UI 反馈): 节点级思考日志, 喂前端 CockpitDashboard "Thought Stream".
    # query_decompose / query_refiner / rank / synthesize / critic 等 LLM 节点在
    # 调 LLM 前/中/后把"思考步骤" append 到本字段对应 node key 列表.
    # search.py SSE 流在 node_chain_end 时 emit `node_thinking` 事件推前端.
    # 不参与 LangGraph state 路由决策, 仅作 observability.
    thinking_log: Optional[dict]

    # R10.5.55: 用户运行时模式. 'llm' (LLM 检索模式, 不允许 mock fallback)
    # 或 'local' (本地模式, 允许 mock fallback 用于离线演示).
    # 由 /search 入口从 SearchRequest.runtime_mode 注入, agent 节点透传读取.
    # SearchResponse.runtime_mode 也回传这个值, 前端根据它显示"真实/本地"badge.
    runtime_mode: Optional[str]

    # R10.5.55: 流式 thinking 日志队列. 每个 agent 节点的 _step() 调用把消息
    # append 到本字段 (list[str]), graph.astream 流式返回 SSE 时增量 emit.
    # _step_queue 在节点完成时合并进 thinking_log 并清空, 保持原有 observability.
    # 这是 LangGraph 0.2+ astream stream_mode="updates" 的标准 pattern.
    _step_queue: Optional[list]

    # R10.5.93 (升级 1/2/3/4): stance_classifier 节点输出, 供前端 ConsensusMeter
    # 显示. dict 形态: {total, counts: {supporting:N, contrasting:N, ...},
    #   type_counts: {rct:N, ...}, majority_stance, summary}
    # 字段 Optional, 没跑 stance_classifier 节点时 None.
    stance_summary: Optional[dict]
