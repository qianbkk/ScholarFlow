"""
backend.utils.async_helpers — 共享异步助手

R10.5 Fix-Audit-Bounded-Gather: 3 个 agent (citation_expander ×2, search_agent ×1)
复制粘贴同一段 `asyncio.wait_for(gather(...), 60s)` + TimeoutError fallback 模式.
抽到这里统一.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def bounded_gather(
    tasks: list[Awaitable[T]],
    *,
    label: str,
    timeout: float,
    fallback_factory: Any = TimeoutError,
) -> list[T | BaseException]:
    """Bounded gather: 跑多个协程, 总耗时上限 timeout 秒, 超时返回 [fallback] * len(tasks).

    Args:
        tasks: 协程列表 (未启动)
        label: 日志标签 (e.g. 'search_node', 'expand_citations.backward')
        timeout: 总耗时上限 (秒)
        fallback_factory: 超时时填入每个 slot 的占位对象, 默认 TimeoutError

    Returns:
        list[T | BaseException]: 每个 task 的结果 (成功值或异常/超时占位).
        与 asyncio.gather(..., return_exceptions=True) 行为一致, 但有总超时.

    Notes:
        R10.5 Fix-Audit-Leak: wait_for 不会自动 cancel 内部 task. 超时后底层 task
        还会跑一会, 持有 semaphore / 连接池. 调用方需要的话可自己追踪 task.
    """
    try:
        return await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"[{label}] gather timed out after {timeout}s, {len(tasks)} tasks pending"
        )
        return [fallback_factory(f"{label} gather timeout")] * len(tasks)
