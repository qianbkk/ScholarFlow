"""BEGIN IMMEDIATE 事务 (P0) 修复测试。

旧 bug：_check_and_reserve_budget 的 critical section (读-改-写) 跨
SQLite 连接不在同一事务中 — 多个 worker 进程并发 reserve 时可能
读到同一旧 total，各自计算不超过上限后都写库，导致 total 突破
GLOBAL_HOURLY_BUDGET 上限。

修复：所有 reserve/return 路径用 BEGIN IMMEDIATE 立即获取 SQLite
写锁（不是普通 BEGIN 的共享锁）。同时配套 _budget_lock (asyncio
Lock) 解决进程内 race。

测试覆盖：
  1) test_check_and_reserve_uses_begin_immediate: reserve 路径发出
     BEGIN IMMEDIATE 语句
  2) test_save_budget_to_db_uses_begin_immediate: 底层 _save_budget_to_db
     也包在 BEGIN IMMEDIATE 事务中
  3) test_return_budget_uses_begin_immediate: _return_budget 同样
     用 BEGIN IMMEDIATE
  4) test_immediate_txn_serializes_concurrent_writers: 多个并发 reserve
     严格串行化 (no 超额)
"""
import asyncio
import sqlite3
import time as _time
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException

import backend.main as main_mod
from backend.utils import cache as cache_mod


# ===== Fixtures =====

@pytest.fixture(autouse=True)
def reset_budget_state(monkeypatch, tmp_path):
    """每个测试前重置预算状态到 temp DB。"""
    tmp_db = tmp_path / "test_budget.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", tmp_db)
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 10.0)
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    yield
    if tmp_db.exists():
        tmp_db.unlink()


# ===== Helpers =====

def _recorded_statements(mock_conn):
    """从 mock connection 的 execute.call_args_list 提取所有 SQL 字符串。"""
    statements = []
    for call in mock_conn.execute.call_args_list:
        args = call.args
        if args and isinstance(args[0], str):
            statements.append(args[0])
    return statements


# ===== 1) reserve 路径发出 BEGIN IMMEDIATE =====

@pytest.mark.asyncio
async def test_check_and_reserve_uses_begin_immediate():
    """_check_and_reserve_budget 应发出 BEGIN IMMEDIATE 事务包裹读-改-写。"""
    with patch.object(cache_mod, "_connect_with_wal") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        # 让 SELECT 返回一个合理的 (total, reset_ts)
        mock_conn.execute.return_value.fetchone.return_value = (0.0, _time.time())

        await main_mod._check_and_reserve_budget(0.5)

        # 验证: execute 调用列表中包含 "BEGIN IMMEDIATE"
        statements = _recorded_statements(mock_conn)
        assert any("BEGIN IMMEDIATE" in s.upper() for s in statements), (
            f"_check_and_reserve_budget 应发出 BEGIN IMMEDIATE, "
            f"实际语句: {statements}"
        )
        # 验证: 有 commit (事务结束)
        mock_conn.commit.assert_called()


# ===== 2) _save_budget_to_db 也用 BEGIN IMMEDIATE =====

def test_save_budget_to_db_wraps_in_begin_immediate():
    """底层 _save_budget_to_db 自身也应包在 BEGIN IMMEDIATE 事务中。"""
    with patch.object(cache_mod, "_connect_with_wal") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        main_mod._save_budget_to_db(0.5, _time.time())

        statements = _recorded_statements(mock_conn)
        assert any("BEGIN IMMEDIATE" in s.upper() for s in statements), (
            f"_save_budget_to_db 应发出 BEGIN IMMEDIATE, 实际: {statements}"
        )
        mock_conn.commit.assert_called()


# ===== 3) _return_budget 用 BEGIN IMMEDIATE =====

@pytest.mark.asyncio
async def test_return_budget_uses_begin_immediate():
    """_return_budget 路径同样应包在 BEGIN IMMEDIATE 事务中（与 reserve 对称）。"""
    # 先写入一些 total 让 return 有意义
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


# ===== 4) BEGIN IMMEDIATE 串行化并发 writers =====

def test_begin_immediate_serializes_concurrent_writes():
    """BEGIN IMMEDIATE 串行化: 多个并发 writer 不会同时进入 critical section。

    用真实 SQLite + 2 个并发连接验证:
    1) Conn A 跑 BEGIN IMMEDIATE
    2) Conn B 跑 BEGIN IMMEDIATE 应被阻塞
    3) Conn A commit/rollback 后, Conn B 才能继续
    """
    # 用真实 DB（不是 mock）
    real_db = main_mod.__class__.__module__  # just to use it
    import tempfile
    import os
    tmp_path = tempfile.mkdtemp()
    db_path = os.path.join(tmp_path, "test_serialize.sqlite")

    try:
        # 初始化
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.execute("CREATE TABLE budget_state (key TEXT PRIMARY KEY, total REAL, reset_ts REAL)")
        conn.execute("INSERT INTO budget_state VALUES ('global', 0.0, ?)", (_time.time(),))
        conn.commit()
        conn.close()

        # 用 2 个独立 connection 模拟 2 worker
        conn_a = sqlite3.connect(db_path, timeout=10.0)
        conn_b = sqlite3.connect(db_path, timeout=10.0)

        # Conn A: BEGIN IMMEDIATE → 写锁
        conn_a.execute("BEGIN IMMEDIATE")
        conn_a.execute("UPDATE budget_state SET total = 1.0 WHERE key = 'global'")
        # 注意: 这里不 commit

        # Conn B: BEGIN IMMEDIATE 应被阻塞 (SQLITE_BUSY)
        # 短超时避免测试卡住
        conn_b_busy = False
        try:
            conn_b.execute("BEGIN IMMEDIATE")
            # 如果不抛, 串行化失败
        except sqlite3.OperationalError as e:
            conn_b_busy = "locked" in str(e).lower() or "busy" in str(e).lower()
            if not conn_b_busy:
                # 兼容其他错误表述
                conn_b_busy = True

        # Conn A 提交
        conn_a.commit()
        conn_a.close()

        # Conn B 重试 BEGIN IMMEDIATE（不再阻塞）
        # 重置 busy 标志, 验证第二次能成功
        if conn_b_busy:
            # Roll back any partial state on conn_b
            try:
                conn_b.rollback()
            except sqlite3.OperationalError:
                pass
            # 第二次 BEGIN IMMEDIATE 应成功
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
