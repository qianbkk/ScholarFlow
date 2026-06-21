"""R10.5.55: 共享 thinking step helper.

每个 LLM 节点 / 计算节点在关键步骤调用 _step() 把消息 push 到:
1. state["_step_queue"] — 流式 SSE emit (Phase B 改造)
2. state["thinking_log"][node_name] — 节点完成时批量保留 (向后兼容 R10.5.53)

调用模式:
    from backend.agents._step_helper import _step
    _step(state, "search", "🔍 启动多源检索 · N sub_queries")

state 是 dict (LangGraph SearchState). node_name 是该步骤所属节点 key.
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _step(state: dict, node_name: str, msg: str) -> None:
    """R10.5.55: append 一条 thinking 消息到 state.

    Args:
        state: LangGraph SearchState dict (in-place mutation).
        node_name: 节点 key ("query_decompose" / "search" / ...).
        msg: 用户可见的 thinking 步骤消息 (含 emoji 前缀).

    Side effects:
        1. state["_step_queue"].append(msg) — SSE 流式 emit
        2. state["thinking_log"][node_name].append(msg) — 节点完成时批量保留
        3. logger.info(msg) — 后端日志可观测
    """
    # 流式队列 (Phase B SSE 改造用)
    q = state.get("_step_queue")
    if q is None:
        q = []
        state["_step_queue"] = q
    q.append(msg)

    # 批量保留 (向后兼容 R10.5.53)
    log = state.get("thinking_log")
    if log is None:
        log = {}
        state["thinking_log"] = log
    if node_name not in log:
        log[node_name] = []
    log[node_name].append(msg)

    # 后端日志
    logger.info(f"[{node_name}.thinking] {msg}")


__all__ = ["_step"]