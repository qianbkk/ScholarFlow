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

    P1-4 fix (深度审计 §P1-4): wait_for 超时后用 gather._cancel() 主动
    关闭 gather 内部 task, 释放 semaphore / httpx 连接池槽位. 旧实现
    仅靠 gather 内部 CancelledError 传播, httpx.AsyncClient.get()
    可能在 await 点未能及时响应, 持锁超时 → 下次同 batch 阻塞.
    """
    gather_task = asyncio.gather(*tasks, return_exceptions=True)
    try:
        return await asyncio.wait_for(gather_task, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            f"[{label}] gather timed out after {timeout}s, {len(tasks)} tasks pending"
        )
        # 主动 cancel gather 内部 task, 触发 CancelledError 传播到子协程
        gather_task.cancel()
        try:
            await gather_task  # 等待 cancel 真正完成 (释放资源)
        except (asyncio.CancelledError, Exception):
            pass
        return [fallback_factory(f"{label} gather timeout")] * len(tasks)
