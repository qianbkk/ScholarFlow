"""新功能测试: _return_budget 归还实际开销与预留之间的差额。

Root cause (P0): 入口 _check_and_reserve_budget 预留的是 req.budget(用户上限),
但实际 total_cost_usd 通常远低于上限。差额若不归还,会导致后续请求
被错误拒绝(503 全局预算上限已达)。本测试验证 _return_budget 能正确
归还差额,使得 budget pool 只扣实际花费。

测试要点:
  1) reserve(budget=2.0) → total=2.0; return(1.7) → total=0.3 (只扣实际开销)
  2) return(amount=0) 是 no-op,不抛错
  3) return(amount>total) 不会让 total 变负数(下限 0)
  4) 并发 reserve+return 不会突破 budget 上限
"""
import asyncio
import time as _time

import pytest
from fastapi import HTTPException

import backend.main as main_mod
from backend.utils import cache


@pytest.fixture(autouse=True)
def _reset_budget_state(monkeypatch, tmp_path):
    """每个测试前重置预算 counter 和 reset_ts,并将 SQLite DB 指向 temp 文件。"""
    tmp_db = tmp_path / "test_cache.sqlite"
    monkeypatch.setattr(cache, "_DB", tmp_db)
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 1.0)
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    yield
    if tmp_db.exists():
        tmp_db.unlink()


def _read_budget_total() -> float:
    total, _ = main_mod._load_budget_from_db()
    return total


def test_return_reduces_reserve_to_actual_cost():
    """模拟: reserve(budget=2.0) → 实际 cost=0.3 → return(1.7) → total=0.3

    这是 P0 修复的核心场景: 预算池应只反映实际花费,不被 req.budget 过度预留。
    """
    main_mod.GLOBAL_HOURLY_BUDGET = 5.0  # 留足预算避免 reserve 被拒

    async def run():
        # 1) 入口 reserve 2.0
        await main_mod._check_and_reserve_budget(2.0)
        assert abs(_read_budget_total() - 2.0) < 1e-9
        # 2) 请求结束, 实际 cost=0.3, 归还差额 1.7
        actual_cost = 0.3
        await main_mod._return_budget(2.0 - actual_cost)
        # 3) 池中应只剩 0.3 (实际成本)
        assert abs(_read_budget_total() - 0.3) < 1e-9, (
            f"return 后 total 应为 0.3 (实际成本), 实际 {_read_budget_total()}"
        )

    asyncio.run(run())


def test_return_zero_amount_is_noop():
    """return(0) 应是 no-op,不抛错也不修改 total。"""
    main_mod._save_budget_to_db(0.5, _time.time())

    async def run():
        await main_mod._return_budget(0.0)

    asyncio.run(run())
    assert abs(_read_budget_total() - 0.5) < 1e-9


def test_return_amount_exceeding_total_floors_to_zero():
    """return 金额超过 current total 时,total 应被下限保护到 0,不能为负。"""
    main_mod._save_budget_to_db(0.1, _time.time())

    async def run():
        # 想还 1.0 但池中只有 0.1 → total 降到 0
        await main_mod._return_budget(1.0)

    asyncio.run(run())
    total, _ = main_mod._load_budget_from_db()
    assert total == 0.0, f"total 应被 floor 到 0, 实际 {total}"


def test_return_sequential_returns_accumulate():
    """连续多次 return 累加: total 持续下降。"""
    main_mod._save_budget_to_db(1.0, _time.time())

    async def run():
        await main_mod._return_budget(0.3)
        await main_mod._return_budget(0.3)
        await main_mod._return_budget(0.3)

    asyncio.run(run())
    assert abs(_read_budget_total() - 0.1) < 1e-9


def test_concurrent_reserve_return_within_budget():
    """并发 reserve+return: budget 池始终不超 GLOBAL_HOURLY_BUDGET。

    模拟请求模式: N 个请求并发,每个 reserve 0.2 然后 return 0.15 (实际 cost 0.05)。
    最终 total 应 = N * 0.05 (实际累计开销),远低于 N * 0.2 (无 return 时的累计)。
    """
    main_mod.GLOBAL_HOURLY_BUDGET = 1.0

    async def fake_request():
        await main_mod._check_and_reserve_budget(0.2)
        # 模拟实际开销 0.05, 归还 0.15
        await main_mod._return_budget(0.15)

    async def run():
        # 5 个并发请求 (5 * 0.2 = 1.0 = budget 边界, 都能 reserve)
        # 实际累计开销: 5 * 0.05 = 0.25
        await asyncio.gather(*[fake_request() for _ in range(5)])

    asyncio.run(run())
    # 最终 total = 5 * 0.05 = 0.25 (实际开销), 而不是 5 * 0.2 = 1.0
    final = _read_budget_total()
    assert abs(final - 0.25) < 1e-9, (
        f"并发 reserve+return 后 total 应为 0.25 (实际累计开销), 实际 {final}"
    )


def test_return_does_not_increase_total():
    """防御性测试: return 不应让 total 增加 (只减不增)。"""
    main_mod._save_budget_to_db(0.5, _time.time())

    async def run():
        await main_mod._return_budget(0.2)

    asyncio.run(run())
    total, _ = main_mod._load_budget_from_db()
    assert total < 0.5 + 1e-9, f"return 后 total {total} 不应 ≥ 0.5"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
