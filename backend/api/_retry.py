"""
backend.api._retry — 共享 HTTP GET 重试 helper

曾 1:1 复制在 openalex.py:106-124 和 semantic_scholar.py:91-109，合并到此处。

R10.5 Fix-X8: 集成 CircuitBreaker, 连续失败 3 次后 30s 内熔断,
避免 SS/OpenAlex 持续故障时 5 子查询 × 30s 超时 = 150s 纯等待.
调用方应 try/except CircuitOpenError 立即降级到 mock.
"""
import asyncio
import logging

import httpx

from backend.utils.circuit_breaker import CircuitOpenError, CircuitBreaker

logger = logging.getLogger(__name__)

# 3 attempts, 指数退避 0.3s / 0.6s / 1.2s（attempt 0 不 sleep）
_RETRY_DELAYS = (0.3, 0.6, 1.2)


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
    breaker: CircuitBreaker | None = None,
) -> httpx.Response | None:
    """HTTP GET with exponential backoff (3 attempts) + optional CircuitBreaker.

    行为：
      - breaker=given: 受熔断器保护, OPEN 状态直接抛 CircuitOpenError
      - 成功（任意 status code）→ 返回 Response 对象, 熔断器记录 success
      - httpx.TimeoutException / NetworkError / RemoteProtocolError → 指数退避重试
      - 3 次都失败 → 记 error log 并返回 None, 熔断器记录 failure
      - 3 次连续 failure 触发熔断 (failure_threshold=3)

    调用方约定:
      - 业务流 (search_papers / get_references / get_citations) 调此函数
      - 捕获 CircuitOpenError 立即降级到 _mock_fallback, 不要让用户 hang
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0.0,) + _RETRY_DELAYS):
        if breaker is not None and breaker.state.value == "open":
            raise CircuitOpenError(
                f"circuit_breaker[{breaker.name}] OPEN, "
                f"skip retry and degrade immediately"
            )
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=timeout)
            if breaker is not None:
                breaker._record_success()
            return resp
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as exc:
            last_exc = exc
            if breaker is not None:
                breaker._record_failure()
            logger.warning("retry %d/3 for %s: %s", attempt + 1, url, exc)
    logger.error("all retries failed for %s: %s", url, last_exc)
    return None
