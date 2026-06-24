"""
utils.proxy — 集中式代理探测，进程级缓存。
PERF-002 / B-002 修复：
- 解决 _get_proxy() 在 SS / OpenAlex 两个文件中重复
- 解决 5 个端口 × 0.5s 同步阻塞事件循环最多 2.5s
- 启动期探测一次，结果 lru_cache 永久复用
"""
from __future__ import annotations

import asyncio
import os
import socket
from functools import lru_cache


# 国内常用代理端口，按命中概率排序
_PROXY_PORTS = (7890, 7891, 7897, 10809, 1080)


def _detect_proxy() -> str | None:
    """探测系统代理 / 环境变量 / 常见本地端口。最多 0.05s × 5 = 0.25s 阻塞。"""
    # 1) 环境变量（最高优先级）
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        v = os.environ.get(var)
        if v:
            return v
    # 2) Windows 系统代理（urllib 会读注册表）
    try:
        import urllib.request
        proxies = urllib.request.getproxies()
        for key in ("https", "http"):
            if key in proxies and proxies[key] and "127.0.0.1" in proxies[key]:
                return proxies[key]
    except Exception:
        pass
    # 3) 本地常见代理端口（短超时 50ms）
    for port in _PROXY_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                return f"http://127.0.0.1:{port}"
        except (OSError, socket.timeout):
            continue
    return None


@lru_cache(maxsize=1)
def get_proxy() -> str | None:
    """进程内只探测一次。

    sync 版本. lifespan 启动期调用 (run_in_executor 已 offload, 不阻塞事件循环).
    测试 reset_cache() 后可重探测.
    """
    return _detect_proxy()


async def aget_proxy() -> str | None:
    """async 版本: 给 async 上下文 (openalex / semantic_scholar 的 _get_client) 调用.

    Fast path: 缓存已 warm 时直接读 (lru_cache 的 dict 读, O(1) 无线程切换).
    Slow path: cache 未填 (冷启动 lifespan 未预热完 + 请求到达) 才走 asyncio.to_thread.

    设计取舍: 若总是 to_thread, warm 路径每次都付线程池调度 + future 唤醒开销,
    但实际收益只剩"lifespan 未完 + 请求到达"极小竞态. fast path 让稳态零开销.
    """
    if get_proxy.cache_info().currsize > 0:
        return get_proxy()
    return await asyncio.to_thread(get_proxy)


def reset_cache() -> None:
    """测试用：清缓存让下一次调用重新探测。"""
    get_proxy.cache_clear()
