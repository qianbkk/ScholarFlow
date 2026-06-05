"""H2 修复测试：预算 counter 迁移到 SQLite WAL — 多 worker 原子性。

旧版用进程内 dict + .budget_state.json 文件：
  - 4-worker Gunicorn 部署下：4 个独立进程各持一份 counter，实际预算 × 4
  - .json 文件非原子写入，4 进程同时写时可能损坏

新版：在已有 cache DB（WAL 模式）增加 budget_state 表，跨进程 / 跨 worker 共享。

测试要点：
  1) 状态持久化到 SQLite（不在内存）
  2) 并发 reserve 在 SQLite 层面是原子的（不会超额）
  3) 启动时能从 DB 恢复 state
  4) 跨"进程"模拟：多个 sqlite connection 共享同一 DB 文件
"""
import asyncio
import sqlite3
import time as _time
from pathlib import Path

import pytest
from fastapi import HTTPException

import backend.main as main_mod
from backend.utils import cache


# ===== Fixtures =====

@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """把 cache DB 指向 temp 文件路径（隔离测试）。"""
    tmp = tmp_path / "test_cache.sqlite"
    monkeypatch.setattr(cache, "_DB", tmp)
    # 强制重新初始化表
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    yield tmp
    if tmp.exists():
        tmp.unlink()


# ===== H2 核心测试 =====

def test_budget_state_persisted_to_sqlite(temp_db, monkeypatch):
    """_save_budget_to_db 后，DB 中应能读到正确的 (total, reset_ts)。"""
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 0.10)
    main_mod._save_budget_to_db(0.07, _time.time())

    # 直接用原生 sqlite3 验证（不通过 _load_budget_from_db）
    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute(
            "SELECT total, reset_ts FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert abs(row[0] - 0.07) < 1e-9
    assert row[1] > 0  # reset_ts 是非零时间戳


def test_concurrent_reserves_exceed_budget_one_fails(temp_db, monkeypatch):
    """budget=0.10，3 个并发 reserve 各 0.05，应正好 2 个成功 + 1 个 503。"""
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 0.10)

    async def reserve():
        try:
            await main_mod._check_and_reserve_budget(0.05)
            return True
        except HTTPException:
            return False

    async def run():
        return await asyncio.gather(*[reserve() for _ in range(3)])

    results = asyncio.run(run())
    success_count = sum(1 for r in results if r is True)
    fail_count = sum(1 for r in results if r is False)

    assert success_count == 2, f"expected 2 successes, got {success_count}"
    assert fail_count == 1, f"expected 1 failure, got {fail_count}"

    # DB 中的 total 应为 0.10（恰好 2 个 0.05 累加）
    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert abs(row[0] - 0.10) < 1e-9, f"DB total {row[0]} != expected 0.10"


def test_cross_process_simulation(temp_db, monkeypatch):
    """模拟多 worker：每个 worker 用独立 sqlite3.connection 操作同一 DB 文件。

    1) Worker A reserve 0.04（成功，DB total = 0.04）
    2) Worker B（独立 sqlite3 connection）应能读到 0.04
    3) Worker B 再 reserve 0.04（成功，DB total = 0.08）
    4) Worker A 再 reserve 0.04（应失败：0.08 + 0.04 = 0.12 > 0.10）
    """
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 0.10)

    # 初始：total = 0
    main_mod._save_budget_to_db(0.0, _time.time())

    # Worker A: reserve 0.04
    async def worker_a_reserve_1():
        await main_mod._check_and_reserve_budget(0.04)
    asyncio.run(worker_a_reserve_1())

    # Worker B: 用独立 sqlite3 connection 读 DB，应看到 0.04
    conn_b = sqlite3.connect(str(temp_db))
    try:
        row = conn_b.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn_b.close()
    assert abs(row[0] - 0.04) < 1e-9, f"Worker B 看到的 total 应为 0.04，实际 {row[0]}"

    # Worker B: reserve 0.04（通过 main_mod，total 应为 0.08）
    async def worker_b_reserve():
        await main_mod._check_and_reserve_budget(0.04)
    asyncio.run(worker_b_reserve())

    # Worker A: 再 reserve 0.04（应失败：0.08 + 0.04 > 0.10）
    async def worker_a_reserve_2():
        try:
            await main_mod._check_and_reserve_budget(0.04)
            return True
        except HTTPException:
            return False

    result = asyncio.run(worker_a_reserve_2())
    assert result is False, "第三笔 reserve 应被 503 拒绝"

    # 最终 DB total 应为 0.08（仅前两笔成功）
    conn_final = sqlite3.connect(str(temp_db))
    try:
        row = conn_final.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn_final.close()
    assert abs(row[0] - 0.08) < 1e-9


def test_load_budget_state_on_startup(temp_db, monkeypatch):
    """模拟进程启动：_load_budget_state 应从 DB 恢复 total/reset_ts。"""
    # 预设 DB 中有 total=0.05 的状态
    reset_ts = _time.time() - 60  # 60 秒前，未过期
    main_mod._save_budget_to_db(0.05, reset_ts)
    # 重置进程内缓存
    main_mod._budget_reset_ts = 0.0

    main_mod._load_budget_state()
    # _budget_reset_ts 应被更新为 DB 中的值（未过期 → 保留）
    assert main_mod._budget_reset_ts == reset_ts


def test_load_budget_state_expired_resets(temp_db, monkeypatch):
    """窗口过期时，_load_budget_state 应自动清零 DB total。"""
    # 预设 DB 中有 total=0.05，reset_ts 2 小时前（已过期）
    expired_ts = _time.time() - 7200
    main_mod._save_budget_to_db(0.05, expired_ts)

    main_mod._load_budget_state()

    # DB total 应被清零
    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn.close()
    assert abs(row[0] - 0.0) < 1e-9, f"过期后 DB total 应为 0，实际 {row[0]}"


def test_budget_table_idempotent_init(temp_db):
    """_init_budget_table 多次调用应幂等（不破坏数据）。"""
    # 预设一些数据
    main_mod._save_budget_to_db(0.07, _time.time())

    # 多次调用不应破坏数据
    main_mod._init_budget_table()
    main_mod._init_budget_table()

    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn.close()
    assert abs(row[0] - 0.07) < 1e-9


if __name__ == "__main__":
    # Standalone 调试入口
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
