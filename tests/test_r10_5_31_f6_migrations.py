"""R10.5.31 (F6) DB migration 框架测试.

覆盖:
  1. _schema_migrations 表自动建好
  2. apply_migration() 幂等 (第二次返 False, 不重复跑 SQL)
  3. 4 条 migration (h8_drop_query_col / r10_5_30_password_cols /
     r10_5_28_stream_tokens / r10_5_30_sessions_table) 全部执行过
  4. fresh DB 上跑一次后, _schema_migrations 表里能看到 4 条记录
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_f6_schema_migrations_table_exists_after_init():
    """_init_db_once 跑完后 _schema_migrations 表存在."""
    import backend.utils.cache as _cache
    orig_db = _cache._DB
    try:
        # 用 tmp_path 隔离
        import tempfile
        tmp_db = Path(tempfile.gettempdir()) / "sf_f6_migrations_test.sqlite"
        if tmp_db.exists():
            tmp_db.unlink()
        _cache._DB = tmp_db
        _cache._DB_INITIALIZED = False
        _cache._DB_INITIALIZED_PATH = None
        _cache._init_db_once()

        conn = _cache._connect_with_wal()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='_schema_migrations'"
            ).fetchone()
            assert row is not None, "_schema_migrations 表没建"
        finally:
            conn.close()
    finally:
        _cache._DB = orig_db
        _cache._DB_INITIALIZED = False
        _cache._DB_INITIALIZED_PATH = None


def test_f6_apply_migration_idempotent():
    """apply_migration 第二次返 False, 不会重跑 SQL."""
    from backend.utils.cache import _init_migrations_table, apply_migration, _connect_with_wal

    call_count = {"n": 0}

    def _fake_migration(conn):
        call_count["n"] += 1

    first = apply_migration("test_f6_idempotent_xxx", _fake_migration)
    second = apply_migration("test_f6_idempotent_xxx", _fake_migration)
    third = apply_migration("test_f6_idempotent_xxx", _fake_migration)

    assert first is True, "首次应返 True"
    assert second is False, "第二次应返 False (幂等)"
    assert third is False
    assert call_count["n"] == 1, f"SQL 应只跑 1 次, 实际 {call_count['n']}"

    # 清理
    conn = _connect_with_wal()
    try:
        conn.execute("DELETE FROM _schema_migrations WHERE name='test_f6_idempotent_xxx'")
        conn.commit()
    finally:
        conn.close()


def test_f6_all_4_migrations_registered():
    """fresh DB 跑一次后, _schema_migrations 表有 4 条记录."""
    import backend.utils.cache as _cache
    orig_db = _cache._DB
    try:
        import tempfile
        tmp_db = Path(tempfile.gettempdir()) / "sf_f6_4_migrations_test.sqlite"
        if tmp_db.exists():
            tmp_db.unlink()
        _cache._DB = tmp_db
        _cache._DB_INITIALIZED = False
        _cache._DB_INITIALIZED_PATH = None
        _cache._init_db_once()

        conn = _cache._connect_with_wal()
        try:
            names = {
                row[0]
                for row in conn.execute("SELECT name FROM _schema_migrations").fetchall()
            }
        finally:
            conn.close()

        expected = {
            "h8_drop_query_col",
            "r10_5_30_password_cols",
            "r10_5_28_stream_tokens",
            "r10_5_30_sessions_table",
        }
        missing = expected - names
        assert not missing, f"F6 missing migrations: {missing}. Got: {names}"
    finally:
        _cache._DB = orig_db
        _cache._DB_INITIALIZED = False
        _cache._DB_INITIALIZED_PATH = None


def test_f6_password_cols_migration_adds_columns():
    """旧 users 表没 password_hash 列 → 跑 migration 后 3 列都有."""
    import backend.utils.cache as _cache
    orig_db = _cache._DB
    try:
        import tempfile
        tmp_db = Path(tempfile.gettempdir()) / "sf_f6_pwd_cols_test.sqlite"
        if tmp_db.exists():
            tmp_db.unlink()
        _cache._DB = tmp_db
        _cache._DB_INITIALIZED = False
        _cache._DB_INITIALIZED_PATH = None
        _cache._init_db_once()

        conn = _cache._connect_with_wal()
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
        finally:
            conn.close()

        for col in ("password_hash", "password_salt", "password_updated_at"):
            assert col in cols, f"F6: users 表缺 {col} 列, cols={cols}"
    finally:
        _cache._DB = orig_db
        _cache._DB_INITIALIZED = False
        _cache._DB_INITIALIZED_PATH = None


def test_f6_sessions_and_stream_tokens_tables_exist():
    """sessions + stream_tokens 表都建好."""
    import backend.utils.cache as _cache
    orig_db = _cache._DB
    try:
        import tempfile
        tmp_db = Path(tempfile.gettempdir()) / "sf_f6_tables_test.sqlite"
        if tmp_db.exists():
            tmp_db.unlink()
        _cache._DB = tmp_db
        _cache._DB_INITIALIZED = False
        _cache._DB_INITIALIZED_PATH = None
        _cache._init_db_once()

        conn = _cache._connect_with_wal()
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()

        assert "sessions" in tables, "F6: sessions 表没建"
        assert "stream_tokens" in tables, "F6: stream_tokens 表没建"
    finally:
        _cache._DB = orig_db
        _cache._DB_INITIALIZED = False
        _cache._DB_INITIALIZED_PATH = None
