"""
LangGraph 图组装。
"""
from langgraph.graph import StateGraph, START, END
from backend.models.state import SearchState
from backend.agents.query_decomposer import query_decompose_node
from backend.agents.search_agent import search_node
from backend.agents.citation_expander import expand_citations_node
from backend.agents.ranker_agent import rank_node
from backend.agents.query_refiner import query_refine_node
from backend.agents.synthesis_agent import synthesize_node
from backend.agents.graph_builder import build_graph_node
from backend.agents.cost_tracker import track_cost_node
from backend.agents.critic_agent import critic_review_node
# R10.5.93 (升级 1/2/3/4): stance_classifier 节点, 跟 critic_review 串联
from backend.agents.stance_classifier import classify_papers_node
from backend.workflow.router import should_refine


def build_search_graph():
    graph = StateGraph(SearchState)

    # 注册节点
    graph.add_node("query_decompose", query_decompose_node)
    graph.add_node("search", search_node)
    graph.add_node("expand_citations", expand_citations_node)
    graph.add_node("rank", rank_node)
    graph.add_node("refine", query_refine_node)
    # R10.5.93: classify_papers 插入到 rank → critic_review 之间
    graph.add_node("classify_papers", classify_papers_node)
    graph.add_node("critic_review", critic_review_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("build_graph", build_graph_node)
    graph.add_node("track_cost", track_cost_node)

    # 主流程边
    graph.add_edge(START, "query_decompose")
    graph.add_edge("query_decompose", "search")
    graph.add_edge("search", "expand_citations")
    graph.add_edge("expand_citations", "rank")

    # 条件分支：优化 or 进入评审/合成流程
    # Phase 3: Critic Agent 红蓝对抗 - 在 rank 之后、synthesize 之前进行独立评审
    # R10.5.93: 升级后变成 rank → classify_papers → critic_review → synthesize
    # 如果需要 refine，则回到 search；否则进入 classify_papers → critic_review
    graph.add_conditional_edges(
        "rank",
        should_refine,
        {"refine": "refine", "synthesize": "classify_papers"},
    )

    # 迭代回路
    graph.add_edge("refine", "search")

    # R10.5.93: classify → critic → synthesize
    graph.add_edge("classify_papers", "critic_review")
    graph.add_edge("critic_review", "synthesize")
    graph.add_edge("synthesize", "build_graph")
    graph.add_edge("build_graph", "track_cost")
    graph.add_edge("track_cost", END)

    return graph.compile()


# 全局单例，避免重复构建
search_graph = build_search_graph()


# Phase 1: 节点元数据 - 用于态势感知驾驶舱
# 每个节点的模型偏好、成本等级、描述信息
NODE_METADATA = {
    "query_decompose": {
        "display_name": "查询分解",
        "model_tier": "flagship",  # flagship / balanced / lightweight
        "default_model": "claude-3-5-sonnet",
        "description": "将用户查询拆解为结构化子问题",
        "icon": "decompose",
    },
    "search": {
        "display_name": "双源检索",
        "model_tier": "lightweight",
        "default_model": "glm-4-flash",
        "description": "从 Semantic Scholar + OpenAlex 并行检索",
        "icon": "search",
    },
    "expand_citations": {
        "display_name": "引文扩展",
        "model_tier": "balanced",
        "default_model": "gpt-4o-mini",
        "description": "基于种子论文扩展引用网络",
        "icon": "expand",
    },
    "rank": {
        "display_name": "三维排序",
        "model_tier": "lightweight",
        "default_model": "glm-4-flash",
        "description": "权威性/相关性/一致性三维打分",
        "icon": "rank",
    },
    "refine": {
        "display_name": "查询优化",
        "model_tier": "flagship",
        "default_model": "claude-3-5-sonnet",
        "description": "基于上一轮结果优化查询策略",
        "icon": "refine",
    },
    # R10.5.93: 立场 / 类型 / 引用 分类节点 (Scite + Consensus + Elicit 借鉴)
    "classify_papers": {
        "display_name": "立场分类",
        "model_tier": "balanced",
        "default_model": "gpt-4o-mini",
        "description": "标注每篇论文立场 (支持/反对) + 研究类型 + 关键引用",
        "icon": "tag",
    },
    "synthesize": {
        "display_name": "综述生成",
        "model_tier": "flagship",
        "default_model": "claude-3-5-sonnet",
        "description": "编织结构化文献综述报告",
        "icon": "synthesize",
    },
    "build_graph": {
        "display_name": "图谱构建",
        "model_tier": "lightweight",
        "default_model": "glm-4-flash",
        "description": "构建 D3 力导向引用图谱",
        "icon": "graph",
    },
    "track_cost": {
        "display_name": "成本追踪",
        "model_tier": "lightweight",
        "default_model": "glm-4-flash",
        "description": "汇总 Token 用量与成本",
        "icon": "cost",
    },
}
