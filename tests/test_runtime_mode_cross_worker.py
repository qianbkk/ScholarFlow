"""R10.5.43 测试: Cross-worker runtime mode 一致性 (P0 multi-worker drift 修复).

R10.5.51 cleanup (BACKLOG D-007): 删 _RuntimeModeProxy dict-subclass 后向兼容 shim.
原覆盖项 4-5 改成 set_runtime_mode() / get_runtime_mode() 显式 API.

覆盖:
  1. set_runtime_mode("mock") 写 SQLite → 新 "worker" (invalidate cache) 立即看到
  2. 1s 进程内缓存: 连续 get 在 TTL 内走缓存
  3. _invalidate_cache() 强制下次 get 立即从 DB 重读
  4. (原) _runtime_mode_override proxy 写 → (现) set_runtime_mode() 写 SQLite
  5. (原) _runtime_mode_override.get 读 → (现) get_runtime_mode() 读 SQLite
  6. is_runtime_mock() 优先级不受 set_runtime_mode 影响 (mock/real/auto)
  7. 持久性: set 后 SQLite 表行可见 (跨进程共享证据)
  8. 非法 mode 防御: DB 写入会校验, 读出非法值兜底 'auto'
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """每个测试前:
    - 把 cache _DB 切到 tmp_path (避免污染 dev/prod 数据)
    - reset 进程内 cache + 删 SQLite 单行

    R10.5.51: _ensure_table() 已删 (cache migration 负责建表). 改用
    cache._init_db_once() 触发 migration, 然后 DELETE 清残留 row.
    """
    from backend.utils import cache as cache_mod
    from backend.utils import runtime_mode as rm

    db_path = tmp_path / "test_cross_worker.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    # 删掉旧表, 让 migration 重新建 (清残留 row)
    db_path.unlink(missing_ok=True)
    # 触发 migration 建表 + 清行
    try:
        rm._invalidate_cache()  # 防止旧 cache 命中
        from backend.utils.cache import _init_db_once, _connect_with_wal
        _init_db_once()  # 触发 _m_r10_5_43_runtime_mode_state migration
        conn = _connect_with_wal()
        try:
            conn.execute("DELETE FROM runtime_mode_state WHERE id=1")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    rm._invalidate_cache()
    yield


# ===== 1. Cross-worker visibility (核心 P0 修复) =====

def test_set_writes_to_sqlite_new_worker_sees_immediately():
    """set_runtime_mode("mock") 写 SQLite → invalidate cache 后立即看到.

    模拟场景: Worker A set "mock" → Worker B (不同 cache) 读 → 看到 "mock".
    """
    from backend.utils import runtime_mode as rm

    # 初始: auto (DB 无行)
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "auto"

    # Worker A: set mock
    rm.set_runtime_mode("mock")

    # Worker B: 模拟新进程, 强制 invalidate cache
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "mock", (
        "Cross-worker drift! Worker B should see mock after Worker A set it."
    )


def test_set_real_writes_to_sqlite_new_worker_sees():
    """set_runtime_mode("real") 同样写 SQLite, 新 worker 看到 real."""
    from backend.utils import runtime_mode as rm

    rm.set_runtime_mode("mock")
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "mock"

    # 切到 real
    rm.set_runtime_mode("real")
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "real"


def test_set_auto_writes_to_sqlite_new_worker_sees():
    """set_runtime_mode("auto") 写 SQLite, 新 worker 看到 auto."""
    from backend.utils import runtime_mode as rm

    rm.set_runtime_mode("real")
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "real"

    rm.set_runtime_mode("auto")
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "auto"


# ===== 2. 1s 进程内缓存 (TTL) =====

def test_cache_hit_within_ttl():
    """连续 get 在 1s 内走 cache, 不查 DB. 验证: 修改 DB 不会立即被看到."""
    from backend.utils import runtime_mode as rm

    rm.set_runtime_mode("mock")
    rm._invalidate_cache()
    first = rm.get_runtime_mode()
    assert first == "mock"

    # 直接改 DB (绕过 set_runtime_mode) 模拟"其他 worker 写"
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        conn.execute(
            "UPDATE runtime_mode_state SET mode=? WHERE id=1", ("real",)
        )
        conn.commit()
    finally:
        conn.close()

    # 在 TTL 内: cache 仍是 mock
    second = rm.get_runtime_mode()
    assert second == "mock", (
        f"Expected cache hit 'mock' within 1s TTL, got {second!r}"
    )


def test_cache_miss_after_ttl():
    """跨过 1s TTL 后, get 重新从 DB 读. 验证: 其他 worker 的写入最终可见."""
    from backend.utils import runtime_mode as rm

    rm.set_runtime_mode("mock")
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "mock"

    # 改 DB
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        conn.execute(
            "UPDATE runtime_mode_state SET mode=? WHERE id=1", ("real",)
        )
        conn.commit()
    finally:
        conn.close()

    # 等 1.1s 跨过 TTL
    time.sleep(1.1)
    # 这次必须看到 "real"
    val = rm.get_runtime_mode()
    assert val == "real", (
        f"After 1s TTL, expected 'real' from DB, got {val!r}"
    )


# ===== 3. _invalidate_cache() 强制立即刷新 =====

def test_invalidate_cache_forces_immediate_refresh():
    """_invalidate_cache() 后, 下次 get 立即从 DB 读 (跳过 TTL)."""
    from backend.utils import runtime_mode as rm

    rm.set_runtime_mode("mock")
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "mock"

    # 改 DB
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        conn.execute(
            "UPDATE runtime_mode_state SET mode=? WHERE id=1", ("real",)
        )
        conn.commit()
    finally:
        conn.close()

    # 不等 TTL, 直接 invalidate → 立即看到 "real"
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "real"


# ===== 4. 向后兼容: set_runtime_mode() 写 SQLite (替代 _runtime_mode_override["mode"] = ...) =====

def test_set_runtime_mode_writes_to_sqlite():
    """R10.5.51 cleanup: set_runtime_mode("mock") 替代旧 proxy["mode"] = "mock", 行为一致 (写 SQLite)."""
    from backend.utils import runtime_mode as rm

    rm.set_runtime_mode("mock")
    # 新 worker 视角: invalidate 后必须看到 mock
    rm._invalidate_cache()
    assert rm.get_runtime_mode() == "mock"

    # 直接查 DB 也能看到 (证据: 真的写到 SQLite 了)
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        row = conn.execute(
            "SELECT mode FROM runtime_mode_state WHERE id=1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "mock"


def test_get_runtime_mode_reads_from_sqlite():
    """R10.5.51 cleanup: get_runtime_mode() 替代旧 proxy["mode"] 读, 行为一致 (从 SQLite 读)."""
    from backend.utils import runtime_mode as rm

    # 先用 set_runtime_mode 写 SQLite
    rm.set_runtime_mode("real")
    rm._invalidate_cache()

    # 直接读 → 应该看到 "real" (从 SQLite 来的)
    assert rm.get_runtime_mode() == "real"


# ===== 5. is_runtime_mock() 集成 =====

def test_is_runtime_mock_reflects_sqlite_state():
    """is_runtime_mock() 读 SQLite, 切换后立即反映 (invalidate 后)."""
    from backend.utils import runtime_mode as rm

    # 初始: 走 env (conftest 设 OPEN_MODE=true + 测试 env 可能 LLM_MOCK)
    # 不强断初始值, 但 mock/real/auto 切换后必须立即生效
    rm.set_runtime_mode("mock")
    rm._invalidate_cache()
    assert rm.is_runtime_mock() is True

    rm.set_runtime_mode("real")
    rm._invalidate_cache()
    assert rm.is_runtime_mock() is False

    rm.set_runtime_mode("auto")
    rm._invalidate_cache()
    # auto 走 env: 跟 LLM_MOCK env 走
    val = rm.is_runtime_mock()
    assert isinstance(val, bool)


# ===== 6. 持久性: SQLite 单行 (id=1) =====

def test_db_has_single_row_with_id_1():
    """runtime_mode_state 表永远是单行 (id=1), UPSERT 不增加行数."""
    from backend.utils import runtime_mode as rm

    rm.set_runtime_mode("mock")
    rm.set_runtime_mode("real")
    rm.set_runtime_mode("auto")
    rm.set_runtime_mode("mock")

    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM runtime_mode_state"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1, f"Expected single row (id=1), got {count} rows"


# ===== 7. 非法 mode 防御 =====

def test_invalid_db_value_falls_back_to_auto():
    """DB 里有非法 mode 值 (被手工污染) → 读时兜底 'auto', 不崩溃."""
    from backend.utils import runtime_mode as rm

    # 手工塞非法值
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO runtime_mode_state (id, mode, updated_at) "
            "VALUES (1, ?, ?)",
            ("garbage_value", time.time()),
        )
        conn.commit()
    finally:
        conn.close()

    rm._invalidate_cache()
    val = rm.get_runtime_mode()
    assert val == "auto", (
        f"Invalid DB value should fall back to 'auto', got {val!r}"
    )


# ===== 8. 并发: 多线程同时 set =====

def test_concurrent_set_last_writer_wins():
    """多线程同时 set → 最后写 DB 的赢 (UPSERT 单行, 顺序由 SQLite 决定)."""
    from backend.utils import runtime_mode as rm

    results = []

    def set_mode(m):
        rm.set_runtime_mode(m)  # type: ignore[arg-type]
        results.append(m)

    threads = [
        threading.Thread(target=set_mode, args=("mock",)),
        threading.Thread(target=set_mode, args=("real",)),
        threading.Thread(target=set_mode, args=("auto",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rm._invalidate_cache()
    final = rm.get_runtime_mode()
    # 3 个值都可能出现 (竞态). 验证是其中一个合法值, 不崩溃.
    assert final in ("mock", "real", "auto"), f"Got invalid final mode: {final!r}"
    # 结果在 set 调用过的集合中
    assert final in set(results)
