"""H1 修复测试：原子化 check-and-reserve 关闭 TOCTOU 竞态。

旧实现的窗口期：
    20 个并发请求都读到 total=49.5，check 通过后全部累加 → 69.5（超额 38%）。

新实现：整个 check + reserve 在 `_budget_lock` 临界区内完成，count 和累加是原子操作。
（H2 之后，存储迁移到 SQLite WAL；本测试用 _load_budget_from_db / _save_budget_to_db 操作。）

测试要点：
  1) 并发 reserve 不应突破 GLOBAL_HOURLY_BUDGET 上限
  2) 第一个失败的 reserve 之后，counter 不应再变化
  3) 顺序调用时，预留金额严格累加
  4) 时间窗口过期后，counter 自动清零
"""
import asyncio
import time as _time

import pytest
from fastapi import HTTPException

import backend.main as main_mod
from backend.main import _check_and_reserve_budget


# ===== Fixtures =====

@pytest.fixture(autouse=True)
def _reset_budget_state(monkeypatch, tmp_path):
    """每个测试前重置预算 counter 和 reset_ts，并将 SQLite DB 指向 temp 文件。"""
    from backend.utils import cache
    # 把 cache DB 指向 temp 路径（隔离每个测试）
    tmp_db = tmp_path / "test_cache.sqlite"
    monkeypatch.setattr(cache, "_DB", tmp_db)
    # 设置小 budget 便于测试
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 1.0)
    # 初始化表（带一行 global total=0）
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    yield
    # 清理
    if tmp_db.exists():
        tmp_db.unlink()


def _prime_budget(total: float) -> None:
    """把 budget counter 预热到 total（用于模拟窗口内已有累计开销）。"""
    main_mod._save_budget_to_db(total, _time.time())


def _read_budget_total() -> float:
    """读取当前 budget total（用于断言）。"""
    total, _ = main_mod._load_budget_from_db()
    return total


# ===== H1 核心测试 =====

def test_concurrent_reserves_never_exceed_budget():
    """20 个并发 reserve 在 budget=1.0 / reserve=0.1 / prime=0.5 下，应最多 5 个成功。"""
    _prime_budget(0.5)  # 剩余 0.5 容纳 5 个 0.1

    async def reserve():
        try:
            await _check_and_reserve_budget(0.1)
            return True
        except HTTPException:
            return False

    async def run():
        return await asyncio.gather(*[reserve() for _ in range(20)])

    results = asyncio.run(run())
    success_count = sum(1 for r in results if r is True)
    fail_count = sum(1 for r in results if r is False)

    # 严格断言：5 个成功 + 15 个失败（剩余 0.5 仅容纳 5 个 0.1 的预留）
    assert success_count == 5, f"expected 5 successes, got {success_count}"
    assert fail_count == 15, f"expected 15 failures, got {fail_count}"
    # 关键断言：counter 严格不超 budget（浮点容差 1e-9）
    final_total = _read_budget_total()
    assert final_total <= 1.0 + 1e-9, (
        f"counter {final_total} exceeded budget 1.0"
    )
    # 确认 5 个 0.1 累加后正好 = 1.0
    assert abs(final_total - 1.0) < 1e-9


def test_reserve_exactly_at_budget_boundary():
    """当 total == budget - estimated_cost 时，刚好可以预留（边界条件）。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 0.5
    _prime_budget(0.3)  # 剩余 0.2

    async def run():
        # 两个并发：每个预留 0.2
        # 第一个：0.3 + 0.2 = 0.5 = budget（OK）
        # 第二个：0.5 + 0.2 = 0.7 > budget（503）
        # 但因锁保护，第二个会看到 0.5 + 0.2 而失败
        return await asyncio.gather(
            _check_and_reserve_budget(0.2),
            _check_and_reserve_budget(0.2),
            return_exceptions=True,
        )

    results = asyncio.run(run())
    # 一个成功，一个 HTTPException
    successes = [r for r in results if r is None]
    failures = [r for r in results if isinstance(r, HTTPException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert _read_budget_total() == 0.5


def test_sequential_reserve_strictly_accumulates():
    """顺序调用时，counter 严格累加，不漏算。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 1.0
    _prime_budget(0.0)

    async def run():
        for _ in range(3):
            await _check_and_reserve_budget(0.2)

    asyncio.run(run())
    # 0.0 + 0.2 + 0.2 + 0.2 = 0.6
    assert abs(_read_budget_total() - 0.6) < 1e-9


def test_first_reserve_after_window_expiry_resets():
    """时间窗口过期后，第一次 reserve 应自动清零 counter。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 1.0
    _prime_budget(0.9)  # 旧窗口累计接近上限
    # 把 reset_ts 设为 2 小时前
    main_mod._save_budget_to_db(0.9, _time.time() - 7200)

    async def run():
        await _check_and_reserve_budget(0.1)

    asyncio.run(run())
    # 窗口过期 → 清零 → 新窗口累计 0.1
    assert abs(_read_budget_total() - 0.1) < 1e-9


def test_reserve_too_large_single_call_fails():
    """单次 reserve 大于预算时立即失败（甚至 counter 为 0）。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 0.5
    _prime_budget(0.0)

    async def run():
        try:
            await _check_and_reserve_budget(0.6)
            return None
        except HTTPException as e:
            return e

    result = asyncio.run(run())
    assert isinstance(result, HTTPException)
    assert result.status_code == 503
    # 失败时 counter 不应被污染
    assert _read_budget_total() == 0.0


def test_concurrent_reserves_persist_to_db():
    """并发 reserve 完成后，DB 中的 total 应反映成功的累加（持久化在锁内）。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 1.0
    _prime_budget(0.0)

    async def run():
        await asyncio.gather(
            _check_and_reserve_budget(0.1),
            _check_and_reserve_budget(0.1),
            _check_and_reserve_budget(0.1),
        )

    asyncio.run(run())
    # 3 个并发 reserve → DB 中 total 应为 0.3
    assert abs(_read_budget_total() - 0.3) < 1e-9


if __name__ == "__main__":
    # Standalone 调试入口
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
