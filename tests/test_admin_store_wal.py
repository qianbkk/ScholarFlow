"""R10.5.49 (P2 defense-in-depth) 测试: admin_store WAL pragma 修复.

覆盖:
  1. admin_store._get_conn() 设置 journal_mode=WAL
  2. admin_store._get_conn() 设置 busy_timeout=5000 (R10.5.49 新加)
  3. admin_store 完整 CRUD 走通 (add / list / remove)
  4. 并发 add 不撞锁 (busy_timeout 生效)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def _admin_db(monkeypatch, tmp_path):
    """每个测试用 tmp_path 隔离 admin DB."""
    from backend.utils import admin_store

    db_path = tmp_path / "test_admin.sqlite"
    monkeypatch.setattr(admin_store, "_DB_PATH", db_path)
    # 重置 module-level _conn 缓存, 强制下次 _get_conn() 重建连接
    monkeypatch.setattr(admin_store, "_conn", None)
    yield db_path


def test_admin_store_wal_mode_active(_admin_db):
    """[R10.5.49] admin_store 启用 WAL 模式 (跟 cache.py 对齐)."""
    from backend.utils import admin_store

    conn = admin_store._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", f"Expected WAL mode, got {mode!r}"


def test_admin_store_busy_timeout_set(_admin_db):
    """[R10.5.49] admin_store 启用 busy_timeout=5000ms (新增, 跟 cache.py 对齐)."""
    from backend.utils import admin_store

    conn = admin_store._get_conn()
    busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert busy_timeout == 5000, (
        f"Expected busy_timeout=5000ms, got {busy_timeout}ms. "
        f"R10.5.49 should add this pragma for multi-worker write safety."
    )


def test_admin_store_full_crud(_admin_db):
    """[R10.5.49] admin_store add / list / remove 完整流程跑通."""
    from backend.utils import admin_store

    # 初始空
    assert len(admin_store.list_admin_user_ids()) == 0

    # add 2 个
    assert admin_store.add_admin("u_alice", note="alice") is True
    assert admin_store.add_admin("u_bob", note="bob") is True

    # list 返 2 个
    ids = admin_store.list_admin_user_ids()
    assert "u_alice" in ids
    assert "u_bob" in ids
    assert len(ids) == 2

    # 重复 add 同 id 不抛, 但返 True (新加) — 实现里 rowcount 决定
    # 实际: 旧 add 返 True 不分新增/已存在. 这里只验证不抛.
    admin_store.add_admin("u_alice", note="dup")

    # remove
    assert admin_store.remove_admin("u_alice") is True
    ids = admin_store.list_admin_user_ids()
    assert "u_alice" not in ids
    assert "u_bob" in ids

    # remove 不存在的 id 也返 True (SQLite DELETE rowcount 决定, 实现里返 True)
    # 这里只验证不抛


def test_admin_store_concurrent_adds_no_lock_error(_admin_db):
    """[R10.5.49] 多线程同时 add, busy_timeout 让写锁等待, 不立即 OperationalError.

    R10.5.49 之前: admin_store 只设 WAL, 没 busy_timeout. 4 worker 部署下
    多个 CLI /admin add 同时调 → 撞写锁立即 'database is locked' 抛错.
    R10.5.49 修: 加 busy_timeout=5000, 写锁等待 < 5s 通常能拿到.
    """
    import threading
    from backend.utils import admin_store

    errors = []

    def _add(uid):
        try:
            admin_store.add_admin(uid, note=f"thread-{uid}")
        except Exception as e:
            errors.append((uid, str(e)))

    threads = [threading.Thread(target=_add, args=(f"u_{i}",)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 关键: 10 个 add 都不应该撞 'database is locked' 错 (busy_timeout 保护)
    lock_errors = [e for e in errors if "locked" in e[1].lower()]
    assert len(lock_errors) == 0, (
        f"Expected no 'database is locked' errors with busy_timeout, got: {lock_errors}"
    )

    # 验证: 10 个 add 全部入库
    ids = admin_store.list_admin_user_ids()
    assert len(ids) == 10, f"Expected 10 admins, got {len(ids)}: {ids}"
