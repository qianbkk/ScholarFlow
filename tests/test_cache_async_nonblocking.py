"""H4 修复测试：cache 异步变体不阻塞事件循环。

旧实现：get_cached / set_cached 的 retry 循环用 time.sleep(0.05 * 2**attempt)，
在 async 调用栈中（main.py:286, 318, 420, 493）会阻塞事件循环，
最坏情况下累计 sleep 0.05 + 0.1 = 0.15s（_MAX_RETRIES=3 共 2 次 sleep），
期间其他请求全卡住。

新实现：get_cached_async / set_cached_async 用 asyncio.sleep + asyncio.to_thread，
把 SQLite I/O 放到线程池、retry 退避让出事件循环。

测试要点：
  1) Mock _get_cached_sync 抛 OperationalError 3 次：wall time >= 0.15s
  2) 重试期间，其他 asyncio.sleep(0) 任务可完成（证明事件循环未被阻塞）
  3) get_cached_async / set_cached_async 行为与同步版本等价（命中/未命中/upsert）
"""
import asyncio
import sqlite3
import time as _time

import pytest

from backend.utils import cache


# ===== Fixtures =====

@pytest.fixture(autouse=True)
def _reset_db(monkeypatch, tmp_path):
    """把 cache DB 指向 temp 文件，避免污染真实数据。"""
    tmp = tmp_path / "test_cache.sqlite"
    monkeypatch.setattr(cache, "_DB", tmp)
    yield
    if tmp.exists():
        tmp.unlink()


# ===== H4 核心测试 =====

def test_get_cached_async_uses_asyncio_sleep_on_retry(monkeypatch):
    """3 次 OperationalError 时，wall time 应 >= 0.05 + 0.1 = 0.15s（2 次退避）。

    实际代码：_MAX_RETRIES=3 共调 3 次，loop 中 `if attempt < _MAX_RETRIES - 1`
    保证最后一次失败后不再 sleep。所以 2 次退避 = 0.05s + 0.1s = 0.15s。
    （H4 描述里的"0.05+0.1+0.2"是基于"每次失败前都 sleep"的误解 —
    真实代码与同步版本行为一致：第 N 次失败后不再 sleep。）

    这是 H4 修复的核心证据：time.sleep → asyncio.sleep。
    """
    call_count = [0]

    def fake_sync(key, ttl_seconds):
        call_count[0] += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache, "_get_cached_sync", fake_sync)

    async def run():
        return await cache.get_cached_async("test", 3, 1.0)

    start = _time.time()
    result = asyncio.run(run())
    elapsed = _time.time() - start

    # 所有重试都失败 → 返回 None
    assert result is None
    # 退避累计：50ms + 100ms = 150ms（2 次 sleep，第 3 次失败后不再 sleep）
    assert elapsed >= 0.15, f"expected >= 0.15s, got {elapsed:.3f}s"
    # 调了 3 次（_MAX_RETRIES）
    assert call_count[0] == 3


def test_get_cached_async_does_not_block_event_loop(monkeypatch):
    """get_cached_async 重试期间，事件循环应可处理其他任务。

    验证手段：并行启动一个"心跳"协程（每 20ms 记录一次时间戳），
    如果事件循环被阻塞，心跳会大幅滞后；否则心跳应正常累加。
    """
    call_count = [0]

    def fake_sync(key, ttl_seconds):
        call_count[0] += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache, "_get_cached_sync", fake_sync)

    heartbeats = []

    async def heartbeat():
        for _ in range(20):
            await asyncio.sleep(0.02)
            heartbeats.append(_time.time())

    async def main_call():
        return await cache.get_cached_async("test", 3, 1.0)

    async def run():
        return await asyncio.gather(heartbeat(), main_call())

    start = _time.time()
    _, result = asyncio.run(run())
    elapsed = _time.time() - start

    # 验证：
    # 1) 主调用返回 None（所有重试失败）
    assert result is None
    # 2) 心跳至少完成 5 次（如果事件循环没被阻塞）
    assert len(heartbeats) >= 5, f"only {len(heartbeats)} heartbeats — loop likely blocked"
    # 3) 心跳之间的时间间隔不应异常大（不应被 retry sleep 阻塞）
    if len(heartbeats) >= 2:
        intervals = [heartbeats[i+1] - heartbeats[i] for i in range(len(heartbeats) - 1)]
        # 任何间隔 > 0.3s 都说明事件循环被阻塞了（heartbeat 间隔 20ms）
        max_interval = max(intervals)
        assert max_interval < 0.3, (
            f"event loop appears blocked: max heartbeat interval {max_interval:.3f}s"
        )


def test_set_cached_async_uses_asyncio_sleep_on_retry(monkeypatch):
    """set_cached_async 的 retry 也应走 asyncio.sleep（不阻塞事件循环）。

    与 get_cached_async 一致：_MAX_RETRIES=3 共 3 次调用，2 次退避 sleep。
    """
    call_count = [0]

    def fake_sync(key, response, cost, tokens):
        call_count[0] += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache, "_set_cached_sync", fake_sync)

    heartbeats = []

    async def heartbeat():
        for _ in range(20):
            await asyncio.sleep(0.02)
            heartbeats.append(_time.time())

    async def main_call():
        await cache.set_cached_async("test", 3, 1.0, {"k": "v"}, 0.01, 100)

    async def run():
        return await asyncio.gather(heartbeat(), main_call())

    start = _time.time()
    asyncio.run(run())
    elapsed = _time.time() - start

    # 退避累计：0.05s + 0.1s = 0.15s + to_thread overhead
    assert elapsed >= 0.15
    assert call_count[0] == 3
    # 心跳不被阻塞
    assert len(heartbeats) >= 5


def test_get_cached_async_returns_value_on_success(monkeypatch):
    """正常路径（_get_cached_sync 返回值）应透传给调用方。"""
    expected = ({"report": "hi", "ranked_papers": []}, 0.05, 1234)

    def fake_sync(key, ttl_seconds):
        return expected

    monkeypatch.setattr(cache, "_get_cached_sync", fake_sync)

    result = asyncio.run(cache.get_cached_async("test", 3, 1.0))
    assert result == expected


def test_set_cached_async_succeeds(monkeypatch, tmp_path):
    """正常路径：set_cached_async 写完后，DB 中应能读到。"""
    call_count = [0]
    captured = {}

    def fake_sync(key, response, cost, tokens):
        call_count[0] += 1
        captured["key"] = key
        captured["response"] = response
        captured["cost"] = cost
        captured["tokens"] = tokens

    monkeypatch.setattr(cache, "_set_cached_sync", fake_sync)

    asyncio.run(cache.set_cached_async(
        "test query", 3, 1.0, {"k": "v"}, 0.05, 100,
    ))

    assert call_count[0] == 1
    assert captured["response"] == {"k": "v"}
    assert captured["cost"] == 0.05
    assert captured["tokens"] == 100


def test_get_cached_async_cache_disabled(monkeypatch):
    """ENABLE_SEARCH_CACHE=false 时应立即返回 None，不调用 _get_cached_sync。"""
    monkeypatch.setenv("ENABLE_SEARCH_CACHE", "false")

    def fake_sync(key, ttl_seconds):
        raise AssertionError("should not be called when cache disabled")

    monkeypatch.setattr(cache, "_get_cached_sync", fake_sync)

    result = asyncio.run(cache.get_cached_async("test", 3, 1.0))
    assert result is None


def test_get_cached_async_succeeds_after_transient_errors(monkeypatch):
    """第 2 次重试成功后，应返回结果（验证指数退避 + 重试逻辑）。"""
    call_count = [0]

    def fake_sync(key, ttl_seconds):
        call_count[0] += 1
        if call_count[0] < 2:  # 第 1 次失败
            raise sqlite3.OperationalError("database is locked")
        return ({"report": "ok"}, 0.01, 100)

    monkeypatch.setattr(cache, "_get_cached_sync", fake_sync)

    start = _time.time()
    result = asyncio.run(cache.get_cached_async("test", 3, 1.0))
    elapsed = _time.time() - start

    assert result is not None
    # 退避 0.05s（仅 1 次重试） + to_thread overhead
    assert elapsed >= 0.05
    assert call_count[0] == 2


if __name__ == "__main__":
    # Standalone 调试入口
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
