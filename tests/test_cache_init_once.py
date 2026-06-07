"""cache._init_db_once (P1) 修复测试。

旧 bug：每次 get_cached_async / set_cached_async
都跑一次 _init_db()，重复做 SELECT sqlite_master + PRAGMA table_info
schema 检查，浪费 ~2-5ms 每次调用。

修复：引入模块级 bool 标志 _DB_INITIALIZED，仅首次跑 _init_db()。
旧：每个 cache 操作都 SELECT schema → 浪费
新：首次 init 后置 _DB_INITIALIZED=True → 后续跳过

R9 清理：同步版 get_cached / set_cached 已删(R8 审计报告 — 死代码),
本文件改用 asyncio.run() 包裹 get_cached_async / set_cached_async。

测试覆盖：
  1) test_init_db_once_runs_only_once_per_process: 100 次 get_cached_async 后
     _init_db 仅被调用 1 次（或 0 次，如果 cache 已被模块加载时初始化）
  2) test_db_initialized_flag_starts_false_and_flips: 标志初始为 False，
     第一次 cache 操作后变 True
  3) test_init_db_once_skips_when_already_initialized: 标志已 True 时
     _init_db_once 不再调底层 _init_db
"""
import asyncio

import pytest

from backend.utils import cache as cache_mod


# ===== Fixtures =====

@pytest.fixture
def reset_init_flag(monkeypatch):
    """每个测试前重置 _DB_INITIALIZED 标志。"""
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    yield


# ===== 1) 标志初始为 False =====

def test_db_initialized_flag_starts_false(reset_init_flag):
    """新进程/重置后 _DB_INITIALIZED 应为 False。"""
    assert cache_mod._DB_INITIALIZED is False, (
        "模块级 _DB_INITIALIZED 标志在重置后应为 False"
    )


# ===== 2) 标志在首次 init 后变 True =====

def test_init_db_once_flips_flag_on_first_call(reset_init_flag, tmp_path, monkeypatch):
    """首次调 _init_db_once 后 _DB_INITIALIZED 应变 True。"""
    # 把 cache DB 指向 temp 路径
    db_path = tmp_path / "test_init_flag.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)

    # 重置标志
    assert cache_mod._DB_INITIALIZED is False
    # 调一次 _init_db_once
    cache_mod._init_db_once()
    # 标志应翻转为 True
    assert cache_mod._DB_INITIALIZED is True
    # 实际表应已创建
    assert db_path.exists(), "_init_db_once 应在 DB 文件中建表"


# ===== 3) 多次 get_cached_async 不重跑 _init_db =====

def test_init_db_runs_only_once_across_many_get_cached(reset_init_flag, tmp_path, monkeypatch):
    """100 次 get_cached_async 后 _init_db 实际只跑 1 次。"""
    db_path = tmp_path / "test_init_once.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)

    # 计数 _init_db 实际调用次数
    call_count = {"n": 0}
    original_init_db = cache_mod._init_db

    def counting_init_db():
        call_count["n"] += 1
        original_init_db()

    monkeypatch.setattr(cache_mod, "_init_db", counting_init_db)

    # 调 100 次 get_cached_async（key 都不命中,但会触发 _init_db 路径）
    for i in range(100):
        asyncio.run(cache_mod.get_cached_async(f"q_{i}", max_iterations=3, budget=1.0))

    # 验证: _init_db 实际只跑 1 次 (首次)
    assert call_count["n"] <= 1, (
        f"_init_db 应只跑 1 次 (首次), 实际 {call_count['n']} 次"
    )
    # 同时 _DB_INITIALIZED 应为 True
    assert cache_mod._DB_INITIALIZED is True


# ===== 4) _init_db_once 第二次是 no-op =====

def test_init_db_once_second_call_is_noop(reset_init_flag, tmp_path, monkeypatch):
    """_init_db_once 第二次调用不应再调底层 _init_db。"""
    db_path = tmp_path / "test_idempotent.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)

    call_count = {"n": 0}
    original_init_db = cache_mod._init_db

    def counting_init_db():
        call_count["n"] += 1
        original_init_db()

    monkeypatch.setattr(cache_mod, "_init_db", counting_init_db)

    # 首次
    cache_mod._init_db_once()
    assert call_count["n"] == 1
    # 后续 10 次都应跳过
    for _ in range(10):
        cache_mod._init_db_once()
    assert call_count["n"] == 1, (
        f"_init_db_once 第二次起应是 no-op, 但 _init_db 被调 {call_count['n']} 次"
    )


# ===== 5) get_cached_async 同样受益 =====

@pytest.mark.asyncio
async def test_get_cached_async_uses_init_db_once(reset_init_flag, tmp_path, monkeypatch):
    """async 路径也走 _init_db_once，不直接调 _init_db。"""
    db_path = tmp_path / "test_async_init.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)

    call_count = {"n": 0}
    original_init_db = cache_mod._init_db

    def counting_init_db():
        call_count["n"] += 1
        original_init_db()

    monkeypatch.setattr(cache_mod, "_init_db", counting_init_db)

    # 调 5 次 async get_cached
    for i in range(5):
        result = await cache_mod.get_cached_async(f"q_{i}", max_iterations=3, budget=1.0)
        assert result is None  # 都没缓存

    # 验证: 仅首次调了 _init_db
    assert call_count["n"] == 1, (
        f"async 路径 5 次 get_cached_async 应只调 _init_db 1 次, 实际 {call_count['n']}"
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
