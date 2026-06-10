"""
backend.api._retry — 共享 HTTP GET 重试 helper

曾 1:1 复制在 openalex.py:106-124 和 semantic_scholar.py:91-109，合并到此处。

R10.5 Fix-X8: 集成 CircuitBreaker, 连续失败 3 次后 30s 内熔断,
避免 SS/OpenAlex 持续故障时 5 子查询 × 30s 超时 = 150s 纯等待.
调用方应 try/except CircuitOpenError 立即降级到 mock.

R10.5 Fix-P2-CCC (CCC.txt 关键问题 2): 429 Too Many Requests 触发退避重试
  - 优先读 Retry-After header (SS/OA 标准, 含 delta-seconds + HTTP-date)
  - delta cap 30s, 失败降级到指数退避
  - 5xx 同样重试 (网络瞬时错误)

R10.5 simplify: 修 sleep-before-try bug (旧实现 attempt 0 也 sleep 0.3s,
  浪费每次 429 重试延迟 0.3s). 现在只在 attempt > 0 时 sleep.
"""
import asyncio
import logging
import time
from email.utils import parsedate_to_datetime

import httpx

from backend.utils.circuit_breaker import CircuitOpenError, CircuitBreaker

logger = logging.getLogger(__name__)

# 3 attempts, 指数退避 0.3s / 0.6s / 1.2s（attempt 0 不 sleep）— 网络异常用
_RETRY_DELAYS = (0.3, 0.6, 1.2)
# 429 退避上限, 防 Retry-After 过大 hang 太久
_RETRY_AFTER_CAP_SEC = 30.0
# 触发重试的 status code
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
    breaker: CircuitBreaker | None = None,
) -> httpx.Response | None:
    """HTTP GET with exponential backoff (4 attempts total: 1 initial + 3 retries) + optional CircuitBreaker.

    行为：
      - breaker=given: 受熔断器保护, OPEN 状态直接抛 CircuitOpenError
      - 成功（任意 status code）→ 返回 Response 对象, 熔断器记录 success
      - httpx.TimeoutException / NetworkError / RemoteProtocolError → 指数退避重试
      - 429/5xx 状态码 → 指数退避 + Retry-After 退避 (优先)
      - 用完所有 attempt → 记 error log 并返回 None (网络异常) 或最后响应 (状态码)
      - 3 次连续 failure 触发熔断 (failure_threshold=3)

    注: 调用方必须检查返回值, 不要假设 None = 失败. 状态码路径返回 Response
    (可能 status != 200), 由调用方决定是否降级到 mock.

    调用方约定:
      - 业务流 (search_papers / get_references / get_citations) 调此函数
      - 捕获 CircuitOpenError 立即降级到 _mock_fallback, 不要让用户 hang
      - 调用方应检查 resp.status_code, 非 200 时降级到 mock
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0.0,) + _RETRY_DELAYS):
        if breaker is not None and breaker.state.value == "open":
            raise CircuitOpenError(
                f"circuit_breaker[{breaker.name}] OPEN, "
                f"skip retry and degrade immediately"
            )
        # R10.5 simplify: 修 sleep-before-try bug.
        # 旧实现在 attempt 0 也 sleep delay=0.3s, 即首次 429 也白白等 0.3s
        # 才发第一次请求. 现在 attempt 0 不睡.
        if attempt > 0 and delay:
            await asyncio.sleep(delay)
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in _RETRYABLE_STATUS:
                # 优先 Retry-After header (SS/OA 标准遵守)
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if retry_after is not None and retry_after <= _RETRY_AFTER_CAP_SEC:
                    backoff = retry_after
                else:
                    backoff = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                if attempt < len(_RETRY_DELAYS):
                    logger.warning(
                        "%s retry %d/3 for %s (status=%d, backoff=%.1fs)",
                        breaker.name if breaker else "http",
                        attempt + 1, url, resp.status_code, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                # 已用完所有 attempt, 返最后响应
                if breaker is not None:
                    breaker._record_failure()
                return resp
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


def _parse_retry_after(value: str | None) -> float | None:
    """解析 Retry-After header (秒数或 HTTP-date). 返 None 表示无法解析.

    RFC 9110 §10.2.3 允许两种格式:
      - delta-seconds:  "120"  →  120s 后重试
      - HTTP-date:      "Wed, 21 Oct 2015 07:28:00 GMT"  →  该时刻之后重试
    """
    if not value:
        return None
    # 优先尝试 delta-seconds (数字字符串)
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    # 回退: HTTP-date 解析 (stdlib email.utils.parsedate_to_datetime)
    try:
        dt = parsedate_to_datetime(value)
        if dt is None:
            return None
        return max(0.0, dt.timestamp() - time.time())
    except (TypeError, ValueError):
        return None

