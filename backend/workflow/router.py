"""
条件路由：决定 rank 之后是 refine 还是 synthesize。
"""
import logging
import os

from backend.config import (
    ROUTER_QUALITY_THRESHOLD_REL,
    ROUTER_QUALITY_THRESHOLD_PAPERS,
)
from backend.models.state import SearchState

logger = logging.getLogger(__name__)


# FIX: 预算边际从绝对值 ($0.3) 改为比例 (默认 15%)。
# 旧实现: budget=0.5 时 $0.3 margin = 60% 预算; budget=20 时 $0.3 margin = 1.5% 预算 — 不可接受。
# 新实现: 剩余预算 / budget < ratio 时停止。默认 0.15 表示剩余 <15% 即停止。
# 旧 env var ROUTER_BUDGET_SAFETY_MARGIN (绝对值) 在 config.py 中保留以做向后兼容
# (读 0.3 时会等价于"剩余 70% 才停",无意义,所以这里只用新名 + 默认 0.15)。
ROUTER_BUDGET_SAFETY_MARGIN_RATIO = float(
    os.getenv("ROUTER_BUDGET_SAFETY_MARGIN_RATIO", "0.15")
)


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

    # FIX: 预算检查改为比例阈值。budget<=0 时不做预算检查（视为无预算约束）。
    if budget > 0:
        remaining_ratio = (budget - cost) / budget
        if remaining_ratio < ROUTER_BUDGET_SAFETY_MARGIN_RATIO:
            logger.info(
                f"[Router] Low budget (${cost:.3f}/${budget:.2f}, "
                f"remaining_ratio={remaining_ratio:.2%} < "
                f"threshold={ROUTER_BUDGET_SAFETY_MARGIN_RATIO:.0%}) -> synthesize"
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
