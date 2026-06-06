"""
条件路由：决定 rank 之后是 refine 还是 synthesize。
"""
import logging

from backend.config import (
    ROUTER_QUALITY_THRESHOLD_REL,
    ROUTER_QUALITY_THRESHOLD_PAPERS,
    ROUTER_BUDGET_SAFETY_MARGIN,
)
from backend.models.state import SearchState

logger = logging.getLogger(__name__)


def should_refine(state: SearchState) -> str:
    """
    决定是继续迭代优化（refine）还是直接综述（synthesize）。
    返回值必须是 "refine" 或 "synthesize"。
    """
    iteration = state.get("iteration", 0) or 0
    max_iter = state.get("max_iterations", 3) or 3
    cost = state.get("total_cost_usd", 0.0) or 0.0
    budget = state.get("budget_limit_usd", 2.0) or 2.0
    ranked = state.get("ranked_papers") or []

    # 强制停止条件
    if iteration >= max_iter:
        logger.info(f"[Router] Max iterations ({max_iter}) reached -> synthesize")
        return "synthesize"

    if budget - cost < ROUTER_BUDGET_SAFETY_MARGIN:
        logger.info(
            f"[Router] Low budget (${cost:.3f}/${budget:.2f}, "
            f"margin={ROUTER_BUDGET_SAFETY_MARGIN}) -> synthesize"
        )
        return "synthesize"

    if len(ranked) < 5:
        logger.info(f"[Router] Too few papers ({len(ranked)}) -> refine")
        return "refine"

    # 质量检查：Top5 平均相关性
    top5 = ranked[:5]
    avg_relevance = sum((p.get("relevance_score", 0) or 0) for p in top5) / len(top5)

    if (
        avg_relevance >= ROUTER_QUALITY_THRESHOLD_REL
        and len(ranked) >= ROUTER_QUALITY_THRESHOLD_PAPERS
    ):
        logger.info(
            f"[Router] Good quality "
            f"(avg_rel={avg_relevance:.1f}>={ROUTER_QUALITY_THRESHOLD_REL}, "
            f"n={len(ranked)}>={ROUTER_QUALITY_THRESHOLD_PAPERS}) -> synthesize"
        )
        return "synthesize"

    logger.info(
        f"[Router] Needs improvement (avg_rel={avg_relevance:.1f}, n={len(ranked)}) -> refine"
    )
    return "refine"
