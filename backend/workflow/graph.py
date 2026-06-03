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
from backend.workflow.router import should_refine


def build_search_graph():
    graph = StateGraph(SearchState)

    # 注册节点
    graph.add_node("query_decompose", query_decompose_node)
    graph.add_node("search", search_node)
    graph.add_node("expand_citations", expand_citations_node)
    graph.add_node("rank", rank_node)
    graph.add_node("refine", query_refine_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("build_graph", build_graph_node)
    graph.add_node("track_cost", track_cost_node)

    # 主流程边
    graph.add_edge(START, "query_decompose")
    graph.add_edge("query_decompose", "search")
    graph.add_edge("search", "expand_citations")
    graph.add_edge("expand_citations", "rank")

    # 条件分支：优化 or 合成
    graph.add_conditional_edges(
        "rank",
        should_refine,
        {"refine": "refine", "synthesize": "synthesize"},
    )

    # 迭代回路
    graph.add_edge("refine", "search")

    # 输出流程
    graph.add_edge("synthesize", "build_graph")
    graph.add_edge("build_graph", "track_cost")
    graph.add_edge("track_cost", END)

    return graph.compile()


# 全局单例，避免重复构建
search_graph = build_search_graph()
