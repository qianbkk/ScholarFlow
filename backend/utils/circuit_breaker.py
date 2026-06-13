"""utils.circuit_breaker — 简单的异步熔断器

Fix-X8 (用户反馈 X 报告 P1-8): SS/OpenAlex 持续故障时, 5 子查询 × 30s
超时 = 150s 纯等待. 加熔断器在连续失败后短期拒绝调用, 立即降级到
mock, 避免把故障拖成"用户在 UI 看到加载 150s 才拿到降级结果" 的
灾难体验.

状态机:
  CLOSED     — 正常, 调用直接通过
  OPEN       — 熔断, 直接抛 CircuitOpenError, 调用方立即降级
  HALF_OPEN  — 探测恢复 (1 次试探), 成功 → CLOSED, 失败 → OPEN

线程安全: Python 异步单线程事件循环, 普通赋值已原子, 无需 Lock.

R10.5.19 (P.txt #3) 重要文档:
- ss_breaker / oa_breaker 是**进程级**单例 (Python 模块级全局变量).
- 4-worker Gunicorn 部署下, 每个 worker 进程各持一份 breaker 状态,
  实际失败阈值 = N × failure_threshold (默认 3 × 4 = 12 次跨进程累积).
- 单进程内: 用户 A 触发 OPEN, 30s 内所有其他用户的 SS 请求立即降级
  (这是 P.txt 担忧的场景, 接受为 known limitation).
- 跨进程共享状态: 计划迁移到 Redis INCR + EXPIRE (跟 budget_state 一起),
  排期 R11+.
- 单 worker (uvicorn dev 模式) 部署则无跨进程问题, 行为可预期.

用法:
    breaker = CircuitBreaker(name="semantic_scholar", failure_threshold=3, recovery_timeout=30.0)

    async def call_api():
        async with breaker.guard():
            return await real_api_call()

    # 业务流: 失败时不 hang 30s, 立即 degrade
    try:
        papers = await call_api()
    except CircuitOpenError:
        papers = await mock_fallback(...)
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """熔断器处于 OPEN 状态, 调用方应立即降级, 不要重试."""


class CircuitBreaker:
    def __init__(
        self,
        *,
        name: str = "default",
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        # name: 用于日志标识 (semantic_scholar / openalex 等)
        # failure_threshold: 连续失败 N 次后 OPEN
        # recovery_timeout: OPEN 持续 N 秒后进入 HALF_OPEN
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout = max(1.0, recovery_timeout)
        self._state: CircuitState = CircuitState.CLOSED
        self._failures: int = 0
        self._opened_at: float = 0.0

    @property
    def state(self) -> CircuitState:
        # 自动检测超时恢复 (lazy 状态转移, 不开后台任务)
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._opened_at >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            logger.info(f"[circuit_breaker:{self.name}] OPEN → HALF_OPEN (探测恢复)")
        return self._state

    def _record_success(self) -> None:
        if self._state != CircuitState.CLOSED:
            logger.info(f"[circuit_breaker:{self.name}] {self._state.value} → CLOSED (恢复)")
        self._state = CircuitState.CLOSED
        self._failures = 0

    def _record_failure(self) -> None:
        self._failures += 1
        if self._state == CircuitState.HALF_OPEN:
            # 探测失败, 重新 OPEN
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                f"[circuit_breaker:{self.name}] HALF_OPEN → OPEN (探测仍失败)"
            )
        elif self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                f"[circuit_breaker:{self.name}] CLOSED → OPEN "
                f"(连续失败 {self._failures} 次, recovery_timeout={self.recovery_timeout}s)"
            )

    class _Guard:
        """async context manager: 进入时检查状态, 退出时根据异常/成功记账."""

        def __init__(self, breaker: "CircuitBreaker") -> None:
            self._b = breaker

        async def __aenter__(self) -> "CircuitBreaker._Guard":
            if self._b.state == CircuitState.OPEN:
                raise CircuitOpenError(
                    f"circuit_breaker[{self._b.name}] is OPEN, "
                    f"degrade immediately"
                )
            return self

        async def __aexit__(self, exc_type, exc, tb) -> Optional[bool]:
            if exc is None:
                self._b._record_success()
            else:
                self._b._record_failure()
            return None  # 不吞异常, 让调用方拿到原始错误做降级

    def guard(self) -> "CircuitBreaker._Guard":
        """返回 async context manager. 用法: `async with breaker.guard(): ...`"""
        return CircuitBreaker._Guard(self)


# ===== 模块级单例: SS / OpenAlex 各一个 =====
# 注: 这是模块级单例, 但跟 Fix-F 一样要避免跨请求阻塞. 熔断器本身只
# 记录"过去 N 秒内的失败次数", 不阻塞调用, 故可以共享.
ss_breaker = CircuitBreaker(
    name="semantic_scholar",
    failure_threshold=3,
    recovery_timeout=30.0,
)
oa_breaker = CircuitBreaker(
    name="openalex",
    failure_threshold=3,
    recovery_timeout=30.0,
)
