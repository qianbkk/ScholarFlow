"""
节点级预算硬停止工具（P0-1）

Why
----
入口处的 `_check_and_reserve_budget` 一次性预留 `req.budget`,但 LangGraph
流水线内部(decompose → search → expand → rank → refine → synthesize →
build_graph → track_cost)每一节点都累加 cost。整个流水线可能要 30-180s,
中间若某节点异常涨价(模型变动、token 数激增),cost 可能远超预期。如果
仅在出口处退还 `budget - actual_cost`,中间不会触发任何中止,仍会继续
消耗更多 token 后才退出。

本模块提供轻量辅助:
  * `BudgetExceededError` — 节点 / 流水线层在 cost 超预算时抛出的异常。
  * `check_budget(cost, limit, hard_cap_ratio)` — 纯函数判断是否触发硬停。
  * `BUDGET_GUARD_HARD_CAP_RATIO` — 全局可调的硬停比例 (默认 1.0)。

Usage
-----
SSE event_generator (主战场):
    accumulated.update(state_update)
    if check_budget(accumulated["total_cost_usd"], accumulated["budget_limit_usd"]):
        yield _sse_format({"event": "budget_exceeded", ...})
        return_amount = max(0.0, budget - actual_cost)
        return

Refine 路由 (router.py):
    if cost >= budget:  # 硬上限, 不管 ratio 多少都立即停
        return "synthesize"
"""
from __future__ import annotations

import os
from typing import Optional


# 全局可调: 1.0 = 等于预算即停; 1.05 = 允许 5% 缓冲
BUDGET_GUARD_HARD_CAP_RATIO: float = float(
    os.getenv("BUDGET_GUARD_HARD_CAP_RATIO", "1.0")
)


class BudgetExceededError(Exception):
    """当累计成本超过 `budget_limit_usd` 时抛出。

    用于:
      * LangGraph 节点内部 (e.g. cost_tracker) 在超预算时主动中断;
      * 主入口包装层做 try/except 兜底,返回 budget_exceeded 状态。

    Attributes:
        cost: 触发时的累计成本 (USD)。
        limit: 该请求的预算上限 (USD)。
        node: 可选 — 触发异常的节点名,便于日志/SSE 事件定位。
    """

    def __init__(
        self,
        cost: float,
        limit: float,
        node: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        self.cost = float(cost)
        self.limit = float(limit)
        self.node = node
        if message is None:
            tag = f" after node {node!r}" if node else ""
            message = (
                f"Budget exceeded{tag}: cost=${self.cost:.4f} "
                f">= limit=${self.limit:.2f}"
            )
        super().__init__(message)


def check_budget(
    cost: float,
    limit: float,
    hard_cap_ratio: Optional[float] = None,
) -> bool:
    """判断是否触发预算硬停止。

    Args:
        cost: 累计成本 (USD)。
        limit: 该请求的预算上限 (USD)。
        hard_cap_ratio: 硬停比例 (默认 `BUDGET_GUARD_HARD_CAP_RATIO` = 1.0)。
            * 1.0  表示 cost >= limit 即停 (推荐,严格)
            * 1.05 表示允许 5% 缓冲, 抖动场景不中断
            * 0.5  表示 cost >= limit * 0.5 即停 (激进,留大缓冲)

    Returns:
        True  — 触发硬停止
        False — 未触发,继续

    Notes:
        * `limit <= 0` 时视为"无预算约束/未配置",不触发 (避免误杀)
        * 强制使用 `>=` 比较: cost 刚好等于 limit 也算超,简单且可预测
    """
    if limit is None or limit <= 0:
        # 0 / 负数 / None 都视为未配置预算, 不硬停
        return False
    ratio = BUDGET_GUARD_HARD_CAP_RATIO if hard_cap_ratio is None else hard_cap_ratio
    return float(cost) >= float(limit) * float(ratio)


__all__ = [
    "BudgetExceededError",
    "check_budget",
    "BUDGET_GUARD_HARD_CAP_RATIO",
]
