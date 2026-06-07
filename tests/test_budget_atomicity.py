"""Budget atomicity (E-group, part 1) — merged test suite.

merged from test_budget_race.py, test_budget_sqlite.py,
test_budget_immediate_txn.py on 2026-06-07.

Covers three intertwined fixes:
  H1: atomic check-and-reserve closes the TOCTOU race
  H2: counter migrated to SQLite WAL for multi-worker correctness
  P0: BEGIN IMMEDIATE wraps every reserve/return for cross-process serialization

Sections:
  1) H1 — concurrent reserve never exceeds budget
  2) H2 — counter persisted in SQLite, cross-process safe
  3) P0 — BEGIN IMMEDIATE issued on reserve/return/save paths
"""
import asyncio
import os
import sqlite3
import tempfile
import time as _time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import backend.main as main_mod
from backend.utils import cache as cache_mod


# ===== Fixtures =====

@pytest.fixture(autouse=True)
def _reset_budget_state(monkeypatch, tmp_path):
    """每个测试前重置预算 counter 和 reset_ts，并将 SQLite DB 指向 temp 文件。"""
    tmp_db = tmp_path / "test_budget_atomicity.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", tmp_db)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 1.0)
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    yield


def _prime_budget(total: float) -> None:
    """把 budget counter 预热到 total（用于模拟窗口内已有累计开销）。"""
    main_mod._save_budget_to_db(total, _time.time())


def _read_budget_total() -> float:
    """读取当前 budget total（用于断言）。"""
    total, _ = main_mod._load_budget_from_db()
    return total


def _recorded_statements(mock_conn):
    """从 mock connection 的 execute.call_args_list 提取所有 SQL 字符串。"""
    statements = []
    for call in mock_conn.execute.call_args_list:
        args = call.args
        if args and isinstance(args[0], str):
            statements.append(args[0])
    return statements


# ============================================================
# 1) H1 — atomic check-and-reserve (race protection)
# ============================================================

def test_concurrent_reserves_never_exceed_budget():
    """[from budget_race] 20 个并发 reserve 在 budget=1.0 / reserve=0.1 / prime=0.5 下，应最多 5 个成功。"""
    _prime_budget(0.5)

    async def reserve():
        try:
            await main_mod._check_and_reserve_budget(0.1)
            return True
        except HTTPException:
            return False

    async def run():
        return await asyncio.gather(*[reserve() for _ in range(20)])

    results = asyncio.run(run())
    success_count = sum(1 for r in results if r is True)
    fail_count = sum(1 for r in results if r is False)

    assert success_count == 5, f"expected 5 successes, got {success_count}"
    assert fail_count == 15, f"expected 15 failures, got {fail_count}"
    final_total = _read_budget_total()
    assert final_total <= 1.0 + 1e-9, f"counter {final_total} exceeded budget 1.0"
    assert abs(final_total - 1.0) < 1e-9


def test_reserve_exactly_at_budget_boundary():
    """[from budget_race] total == budget - estimated_cost 时，刚好可以预留（边界条件）。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 0.5
    _prime_budget(0.3)

    async def run():
        return await asyncio.gather(
            main_mod._check_and_reserve_budget(0.2),
            main_mod._check_and_reserve_budget(0.2),
            return_exceptions=True,
        )

    results = asyncio.run(run())
    successes = [r for r in results if r is None]
    failures = [r for r in results if isinstance(r, HTTPException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert _read_budget_total() == 0.5


def test_sequential_reserve_strictly_accumulates():
    """[from budget_race] 顺序调用时，counter 严格累加，不漏算。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 1.0
    _prime_budget(0.0)

    async def run():
        for _ in range(3):
            await main_mod._check_and_reserve_budget(0.2)

    asyncio.run(run())
    assert abs(_read_budget_total() - 0.6) < 1e-9


def test_first_reserve_after_window_expiry_resets():
    """[from budget_race] 时间窗口过期后，第一次 reserve 应自动清零 counter。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 1.0
    _prime_budget(0.9)
    main_mod._save_budget_to_db(0.9, _time.time() - 7200)

    async def run():
        await main_mod._check_and_reserve_budget(0.1)

    asyncio.run(run())
    assert abs(_read_budget_total() - 0.1) < 1e-9


def test_reserve_too_large_single_call_fails():
    """[from budget_race] 单次 reserve 大于预算时立即失败（甚至 counter 为 0）。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 0.5
    _prime_budget(0.0)

    async def run():
        try:
            await main_mod._check_and_reserve_budget(0.6)
            return None
        except HTTPException as e:
            return e

    result = asyncio.run(run())
    assert isinstance(result, HTTPException)
    assert result.status_code == 503
    assert _read_budget_total() == 0.0


def test_concurrent_reserves_persist_to_db():
    """[from budget_race] 并发 reserve 完成后，DB 中的 total 应反映成功的累加。"""
    main_mod.GLOBAL_HOURLY_BUDGET = 1.0
    _prime_budget(0.0)

    async def run():
        await asyncio.gather(
            main_mod._check_and_reserve_budget(0.1),
            main_mod._check_and_reserve_budget(0.1),
            main_mod._check_and_reserve_budget(0.1),
        )

    asyncio.run(run())
    assert abs(_read_budget_total() - 0.3) < 1e-9


# ============================================================
# 2) H2 — counter persisted in SQLite, cross-process safe
# ============================================================

def test_budget_state_persisted_to_sqlite(monkeypatch):
    """[from budget_sqlite] _save_budget_to_db 后，DB 中应能读到正确的 (total, reset_ts)。"""
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 0.10)
    main_mod._save_budget_to_db(0.07, _time.time())

    db_path = cache_mod._DB
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT total, reset_ts FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert abs(row[0] - 0.07) < 1e-9
    assert row[1] > 0


def test_concurrent_reserves_exceed_budget_one_fails(monkeypatch):
    """[from budget_sqlite] budget=0.10，3 个并发 reserve 各 0.05，应正好 2 个成功 + 1 个 503。"""
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

    db_path = cache_mod._DB
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert abs(row[0] - 0.10) < 1e-9, f"DB total {row[0]} != expected 0.10"


def test_cross_process_simulation(monkeypatch):
    """[from budget_sqlite] 模拟多 worker: 每个 worker 用独立 sqlite3 connection 操作同一 DB 文件。"""
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 0.10)
    main_mod._save_budget_to_db(0.0, _time.time())

    db_path = cache_mod._DB

    # Worker A: reserve 0.04
    async def worker_a_reserve_1():
        await main_mod._check_and_reserve_budget(0.04)
    asyncio.run(worker_a_reserve_1())

    # Worker B: 用独立 sqlite3 connection 读 DB
    conn_b = sqlite3.connect(str(db_path))
    try:
        row = conn_b.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn_b.close()
    assert abs(row[0] - 0.04) < 1e-9, f"Worker B 看到的 total 应为 0.04，实际 {row[0]}"

    # Worker B: reserve 0.04
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

    conn_final = sqlite3.connect(str(db_path))
    try:
        row = conn_final.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn_final.close()
    assert abs(row[0] - 0.08) < 1e-9


def test_load_budget_state_on_startup(monkeypatch):
    """[from budget_sqlite] 模拟进程启动：_load_budget_state 应从 DB 恢复 total/reset_ts。"""
    reset_ts = _time.time() - 60
    main_mod._save_budget_to_db(0.05, reset_ts)
    main_mod._budget_reset_ts = 0.0

    main_mod._load_budget_state()
    assert main_mod._budget_reset_ts == reset_ts


def test_load_budget_state_expired_resets(monkeypatch):
    """[from budget_sqlite] 窗口过期时，_load_budget_state 应自动清零 DB total。"""
    expired_ts = _time.time() - 7200
    main_mod._save_budget_to_db(0.05, expired_ts)

    main_mod._load_budget_state()

    db_path = cache_mod._DB
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn.close()
    assert abs(row[0] - 0.0) < 1e-9, f"过期后 DB total 应为 0，实际 {row[0]}"


def test_budget_table_idempotent_init():
    """[from budget_sqlite] _init_budget_table 多次调用应幂等（不破坏数据）。"""
    main_mod._save_budget_to_db(0.07, _time.time())
    main_mod._init_budget_table()
    main_mod._init_budget_table()

    db_path = cache_mod._DB
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT total FROM budget_state WHERE key='global'"
        ).fetchone()
    finally:
        conn.close()
    assert abs(row[0] - 0.07) < 1e-9


# ============================================================
# 3) P0 — BEGIN IMMEDIATE on every write path
# ============================================================

@pytest.mark.asyncio
async def test_check_and_reserve_uses_begin_immediate():
    """[from budget_immediate_txn] _check_and_reserve_budget 应发出 BEGIN IMMEDIATE 事务包裹读-改-写。"""
    with patch.object(cache_mod, "_connect_with_wal") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (0.0, _time.time())

        await main_mod._check_and_reserve_budget(0.5)

        statements = _recorded_statements(mock_conn)
        assert any("BEGIN IMMEDIATE" in s.upper() for s in statements), (
            f"_check_and_reserve_budget 应发出 BEGIN IMMEDIATE, "
            f"实际语句: {statements}"
        )
        mock_conn.commit.assert_called()


def test_save_budget_to_db_wraps_in_begin_immediate():
    """[from budget_immediate_txn] 底层 _save_budget_to_db 自身也应包在 BEGIN IMMEDIATE 事务中。"""
    with patch.object(cache_mod, "_connect_with_wal") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        main_mod._save_budget_to_db(0.5, _time.time())

        statements = _recorded_statements(mock_conn)
        assert any("BEGIN IMMEDIATE" in s.upper() for s in statements), (
            f"_save_budget_to_db 应发出 BEGIN IMMEDIATE, 实际: {statements}"
        )
        mock_conn.commit.assert_called()


@pytest.mark.asyncio
async def test_return_budget_uses_begin_immediate():
    """[from budget_immediate_txn] _return_budget 路径同样应包在 BEGIN IMMEDIATE 事务中。"""
    main_mod._save_budget_to_db(1.0, _time.time())

    with patch.object(cache_mod, "_connect_with_wal") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (1.0, _time.time())

        await main_mod._return_budget(0.3)

        statements = _recorded_statements(mock_conn)
        assert any("BEGIN IMMEDIATE" in s.upper() for s in statements), (
            f"_return_budget 应发出 BEGIN IMMEDIATE, 实际: {statements}"
        )
        mock_conn.commit.assert_called()


def test_begin_immediate_serializes_concurrent_writes():
    """[from budget_immediate_txn] BEGIN IMMEDIATE 串行化: 多个并发 writer 不会同时进入 critical section。"""
    tmp_path = tempfile.mkdtemp()
    db_path = os.path.join(tmp_path, "test_serialize.sqlite")

    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.execute("CREATE TABLE budget_state (key TEXT PRIMARY KEY, total REAL, reset_ts REAL)")
        conn.execute("INSERT INTO budget_state VALUES ('global', 0.0, ?)", (_time.time(),))
        conn.commit()
        conn.close()

        conn_a = sqlite3.connect(db_path, timeout=10.0)
        conn_b = sqlite3.connect(db_path, timeout=10.0)

        conn_a.execute("BEGIN IMMEDIATE")
        conn_a.execute("UPDATE budget_state SET total = 1.0 WHERE key = 'global'")

        conn_b_busy = False
        try:
            conn_b.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            conn_b_busy = "locked" in str(e).lower() or "busy" in str(e).lower()
            if not conn_b_busy:
                conn_b_busy = True

        conn_a.commit()
        conn_a.close()

        if conn_b_busy:
            try:
                conn_b.rollback()
            except sqlite3.OperationalError:
                pass
            conn_b.execute("BEGIN IMMEDIATE")
            conn_b.rollback()

        conn_b.close()
        assert conn_b_busy, (
            "BEGIN IMMEDIATE 应让第二个 writer 等待/失败, "
            "否则串行化失败 (P0 bug 仍存在)"
        )
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
        os.rmdir(tmp_path)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
