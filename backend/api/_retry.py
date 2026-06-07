"""
backend.api._retry — 共享 HTTP GET 重试 helper

曾 1:1 复制在 openalex.py:106-124 和 semantic_scholar.py:91-109，合并到此处。
"""
import asyncio
import logging

import httpx

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
) -> httpx.Response | None:
    """HTTP GET with exponential backoff (3 attempts). Returns None on final failure.

    行为：
      - 成功（任意 status code）→ 返回 Response 对象
      - httpx.TimeoutException / NetworkError / RemoteProtocolError → 指数退避重试
      - 3 次都失败 → 记 error log 并返回 None（caller 需处理 None）

    原 openalex.py / semantic_scholar.py 各自定义 1:1 复制的 _get_with_retry，
    现统一到本 helper，调用方 import 即可。
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0.0,) + _RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await client.get(url, params=params, headers=headers, timeout=timeout)
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as exc:
            last_exc = exc
            logger.warning("retry %d/3 for %s: %s", attempt + 1, url, exc)
    logger.error("all retries failed for %s: %s", url, last_exc)
    return None
