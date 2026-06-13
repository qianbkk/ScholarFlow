"""R10.5.19 P1 修复测试: budget async 函数不阻塞事件循环 (P.txt 审计 #4).

旧实现: async def _check_and_reserve_budget() 函数体内全程同步 sqlite3
(conn.execute / commit). sqlite3 操作持 GIL 期间会阻塞 asyncio 事件循环.

新实现: 抽 `_check_and_reserve_sync` 同步函数, async 函数体
`await asyncio.to_thread(_check_and_reserve_sync, ...)` 把 I/O offload 到
默认 ThreadPoolExecutor.

验证: 在 _check_and_reserve_budget 跑期间, 另一 coroutine 还能跑.
"""
import asyncio
import time as _time

import pytest

from backend.api.services.budget import (
    _check_and_reserve_budget,
    _return_budget,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """清空 budget table, 初始化 budget_state 行."""
    import backend.main as main_mod  # noqa: F401
    from backend.utils import cache as cache_mod
    db_path = tmp_path / "test_nonblock.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    # 初始化 budget_state 表 (R10.5.16 验证惯例)
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    yield


def test_check_and_reserve_does_not_block_event_loop():
    """并发跑: 1 个 _check_and_reserve_budget + 1 个 sleep(0.05) 计数器.
    如果 budget 阻塞事件循环, sleep 计数器会延后.
    """
    counter = {"n": 0}

    async def background_ticks():
        """每秒 ~20 ticks. 50ms × 20 = 1s 总共 ~20 ticks."""
        for _ in range(20):
            await asyncio.sleep(0.05)
            counter["n"] += 1

    async def scenario():
        # 并发跑: budget reserve (同步 SQLite, 100ms 量级) + 后台 ticks
        await asyncio.gather(
            _check_and_reserve_budget(0.1, user_id="dev-user"),
            background_ticks(),
        )

    asyncio.run(scenario())

    # 旧实现: 阻塞 ~50-200ms, ticks 可能 < 18
    # 新实现: to_thread 把 SQLite 移到线程池, ticks 应接近 20
    assert counter["n"] >= 18, (
        f"事件循环被 budget 阻塞, ticks 只跑了 {counter['n']}/20. "
        f"预期 ≥18 (to_thread 修复后). 旧实现可能 < 15."
    )


def test_return_budget_does_not_block_event_loop():
    """_return_budget 同样走 to_thread, 不阻塞."""
    counter = {"n": 0}

    async def background_ticks():
        for _ in range(20):
            await asyncio.sleep(0.05)
            counter["n"] += 1

    async def scenario():
        await asyncio.gather(
            _return_budget(0.05, user_id="dev-user"),
            background_ticks(),
        )

    asyncio.run(scenario())
    assert counter["n"] >= 18, (
        f"事件循环被 _return_budget 阻塞, ticks 只跑了 {counter['n']}/20"
    )
