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
from backend.utils.budget_guard import check_budget  # P0-1: 硬上限辅助

logger = logging.getLogger(__name__)


# FIX: 预算边际从绝对值 ($0.3) 改为比例 (默认 15%)。
# 旧实现: budget=0.5 时 $0.3 margin = 60% 预算; budget=20 时 $0.3 margin = 1.5% 预算 — 不可接受。
# 新实现: 剩余预算 / budget < ratio 时停止。默认 0.15 表示剩余 <15% 即停止。
# 旧 env var ROUTER_BUDGET_SAFETY_MARGIN (绝对值) 在 config.py 中保留以做向后兼容
# (读 0.3 时会等价于"剩余 70% 才停",无意义,所以这里只用新名 + 默认 0.15)。
ROUTER_BUDGET_SAFETY_MARGIN_RATIO = float(
    os.getenv("ROUTER_BUDGET_SAFETY_MARGIN_RATIO", "0.15")
)

# Round 6 S8: router per-iter cost cap $0.3, 防止单次 LLM 异常烧光全部 budget
# 老的 ratio margin (剩余 < 15% 停) 在 budget=2 时剩余阈值 = $0.3 — 看似够用,
# 但单次 refine 调用异常 (e.g. provider 返回异常大的 max_tokens) 可能一次就烧
# $0.5+, 把 ratio margin 直接绕过。这里加硬上限, 在 ratio 检查之前先拦一道。
# 0 是关闭。生产环境建议 0.3 (默认), dev/probe 可设 0 关闭。
PER_ITER_BUDGET_CAP_USD = float(os.getenv("PER_ITER_BUDGET_CAP_USD", "0.3"))


def should_refine(state: SearchState) -> str:
    """
    决定是继续迭代优化（refine）还是直接综述（synthesize）。
    返回值必须是 "refine" 或 "synthesize"。

    P0-1: 在 ratio margin 检查之前,先做一次"硬上限"判断。
        若 cost 已 >= budget, 无论剩余比例是多少, 一律走 synthesize
        (refine 必然再花更多 token, 必超预算)。这是与 SSE 节点级
        硬停止的双重保险: SSE 在 chunk 边界实时停止; router 在 refine
        决策前拦截, 避免下一次 refine 调用白白启动 LLM。

    Round 6 S8: per-iter cost cap, 单次迭代 LLM 异常烧光全部 budget 时强制停。
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

    # P0-1 硬上限: cost >= budget 时立即停, 不管 ratio 多少
    # (check_budget 在 budget<=0 时返回 False, 即视为无预算约束)
    if budget > 0 and check_budget(cost, budget):
        logger.warning(
            f"[Router] P0-1 hard cap reached: cost=${cost:.3f} >= "
            f"budget=${budget:.2f} -> synthesize (skip refine)"
        )
        return "synthesize"

    # Round 6 S8: per-iter cost cap, 单 iter 超过 $0.3 强制 synthesize
    # 在 ratio margin 之前 — per-iter cap 更严格, 先拦; 避免异常 LLM 调用
    # (e.g. 异常 max_tokens / 循环 retry) 一次烧光 $0.3+ 直接绕过 ratio 检查
    # M-A 修复 (P0-2): 旧实现 `cost >= PER_ITER_BUDGET_CAP_USD` 检查的是累计
    # total_cost_usd, 不是本轮增量。注释"单轮超 $0.3 停止"是错的 — 当 iter 2
    # 时累计成本本来就 >= $0.3, 会无脑触发。改用 iter_delta = cost - prev_iter_cost
    # 才是真正的"本轮 LLM 消耗"。prev_iter_cost_usd 由 search_agent 入口在每个
    # iter 开始时写入 (透传到 expand / rank / synth), 准确刻画本 iter 起点。
    if PER_ITER_BUDGET_CAP_USD > 0:
        prev_cost = state.get("prev_iter_cost_usd", 0.0) or 0.0
        iter_delta = cost - prev_cost  # 本轮真实增量
        if iter_delta >= PER_ITER_BUDGET_CAP_USD:
            logger.warning(
                f"[Router] per-iter delta ${iter_delta:.4f} >= cap ${PER_ITER_BUDGET_CAP_USD:.2f}, synthesize"
            )
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
        # R10.5.46 (P1 LangGraph safety net): 连续 0 结果 → 强制收口, 不要再 refine.
        # 场景: 冷门查询 (e.g. "xyzzy" / 拼错术语) → SS/OA 永远 0 → 死磕 budget.
        # 旧实现: papers < 5 → 永远 refine → 3 次空迭代, 浪费 token + budget.
        # 新实现: empty_result_streak >= 2 强制 synthesize, synthesis 收到 streak
        # 标记后给用户友好提示 (建议修改查询措辞).
        streak = int(state.get("empty_result_streak") or 0)
        if streak >= 2:
            logger.warning(
                f"[Router] empty_result_streak={streak} >= 2, "
                f"too few papers ({len(ranked)}) -> force synthesize "
                f"(avoid wasted refine on cold/junk query)"
            )
            return "synthesize"
        logger.info(f"[Router] Too few papers ({len(ranked)}), streak={streak} -> refine")
        return "refine"

    # 质量检查：Top5 平均相关性 + 论文数达标
    # P10 (P1-4 性能): 论文阈值从 hardcode 15 改为 paper_max 动态.
    # 旧实现: 永远 n>=15 不满足 (paper_max=10 默认), max_iter=3 必然跑满 3 轮
    #          → 单 iter 50s × 3 = 150s+ 浪费.
    # 新实现: 用 paper_max 替代 (用户期望的"足够多"上限), paper_max=10 时
    #          n>=10 即触发 synthesize, 实测省 1-2 iter = 50-150s.
    paper_max = int(state.get("paper_max") or 10)
    effective_min_papers = min(ROUTER_QUALITY_THRESHOLD_PAPERS, paper_max)
    top5 = ranked[:5]
    avg_relevance = sum((p.get("relevance_score", 0) or 0) for p in top5) / len(top5)

    if (
        avg_relevance >= ROUTER_QUALITY_THRESHOLD_REL
        and len(ranked) >= effective_min_papers
    ):
        logger.info(
            f"[Router] Good quality "
            f"(avg_rel={avg_relevance:.1f}>={ROUTER_QUALITY_THRESHOLD_REL}, "
            f"n={len(ranked)}>={effective_min_papers} (paper_max={paper_max})) -> synthesize"
        )
        return "synthesize"

    logger.info(
        f"[Router] Needs improvement (avg_rel={avg_relevance:.1f}, n={len(ranked)}, "
        f"min_papers={effective_min_papers}, paper_max={paper_max}) -> refine"
    )
    return "refine"
