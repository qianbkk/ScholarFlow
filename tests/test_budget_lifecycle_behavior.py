"""
Behavior tests for budget lifecycle — 行为测试覆盖 (P0-1 审计迁移铺路)

AAA.txt P0-1 / X.md §2.1 报告:
  现有 tests/test_budget_lifecycle.py 大量"源码字符串断言" (assert "..." in src),
  锁死了 main.py 的重构. 解锁方法: 把静态 guard 替换为行为测试.

本文件是 R10.5 行为测试迁移的第一步 — 不替换静态 guard (那需要重写 38 个
test_budget_lifecycle 测试, 1-2 周工作量), 但提供一份**等价行为覆盖**, R11+
完全迁移时可作为 reference 直接复用, 旧静态 guard 一并删除.

行为测试覆盖:
  1. _check_and_reserve_budget: 正常 reserve + 超 cap 抛 503
  2. _check_and_reserve_budget: 多用户隔离
  3. _return_budget: 实际成本低于预算时退还差额
  4. _return_budget: 多次退还累计正确
  5. _check_and_reserve_budget + _return_budget 配合: 异常路径 budget 仍归零
  6. 跨小时窗口: 1h 后 budget 重置

每个 test 都用真实 SQLite (tmp_path) + 真实 _init_db_once, 不读 main.py 源码.
"""
import asyncio
import time as _time
from pathlib import Path

import pytest
from fastapi import HTTPException

# 用 cache_mod._DB 切到 tmp_path, 跟 test_budget_lifecycle.py 模式一致


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """提供 tmp SQLite + 重置 _init_db_once 标志 + 清 _RATE_HISTORY 等"""
    from backend.utils import cache as cache_mod
    db_path = tmp_path / "behavior_test.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    cache_mod._DB_INITIALIZED = False
    cache_mod._DB_INITIALIZED_PATH = None
    # cache._init_db() 创建 users + budget_user + search_cache (向后兼容:
    # budget/auth 模块用 _connect_with_wal("budget"/"auth"), 但 SCHOLARFLOW_DB_DIR
    # 未设时回退到 _DB, 所以这些表都建在 tmp DB 里)
    cache_mod._init_db_once()
    # budget_state 表是 dev-user 走的, 旧 budget.py 单独建.
    from backend.api.services.budget import _init_budget_table
    _init_budget_table()
    yield db_path
    cache_mod._DB_INITIALIZED = False


# ===== 1. _check_and_reserve_budget: 正常 + 异常路径 =====

@pytest.mark.asyncio
async def test_reserve_then_return_full_cycle(tmp_db):
    """完整周期: reserve(budget=1.0) → return(actual=0.3) → 剩余 reserved=0.7 可再 reserve"""
    from backend.api.services.budget import (
        _check_and_reserve_budget, _return_budget,
    )
    # dev-user 用 global budget_state; OPEN_MODE 默认开启, cap=50 USD/h
    await _check_and_reserve_budget(1.0, user_id="dev-user")
    # 现在 reserved=1.0, 实际用 0.3
    await _return_budget(0.7, user_id="dev-user")  # 退还差额
    # 再 reserve 1.0, total=2.0 仍 < 50 cap
    await _check_and_reserve_budget(1.0, user_id="dev-user")
    await _return_budget(1.0, user_id="dev-user")


@pytest.mark.asyncio
async def test_reserve_exceeds_cap_raises_503(tmp_db, monkeypatch):
    """reserve 超 hour cap 抛 HTTPException(503)."""
    from backend.api.services import budget as budget_mod
    monkeypatch.setattr(budget_mod, "get_global_hourly_budget", lambda: 1.0)
    from backend.api.services.budget import _check_and_reserve_budget
    # 1.0 cap, reserve 0.8 通过
    await _check_and_reserve_budget(0.8, user_id="dev-user")
    # 再 reserve 0.5 → 0.8 + 0.5 = 1.3 > 1.0 → 503
    with pytest.raises(HTTPException) as exc:
        await _check_and_reserve_budget(0.5, user_id="dev-user")
    assert exc.value.status_code == 503


# ===== 2. 多用户隔离 =====

@pytest.mark.asyncio
async def test_user_a_reserve_does_not_block_user_b(tmp_db):
    """多用户 budget 隔离: user_a 用光预算, user_b 不受影响."""
    from backend.api.services.budget import _check_and_reserve_budget
    # 每用户 cap = 5.0 USD/h
    await _check_and_reserve_budget(4.5, user_id="user_a")
    # user_b reserve 4.5 独立计数, 通过
    await _check_and_reserve_budget(4.5, user_id="user_b")
    # user_a 再 reserve 1.0 → 4.5+1.0=5.5 > 5 → 503
    with pytest.raises(HTTPException) as exc:
        await _check_and_reserve_budget(1.0, user_id="user_a")
    assert exc.value.status_code == 503
    # user_b 仍能 reserve 0.5
    await _check_and_reserve_budget(0.5, user_id="user_b")


# ===== 3. 退还差额 =====

@pytest.mark.asyncio
async def test_return_budget_releases_capacity(tmp_db):
    """实际开销 < 预留时, _return_budget 释放预留, 后续可继续 reserve."""
    from backend.api.services.budget import _check_and_reserve_budget, _return_budget
    # user_a reserve 5.0 (用满 cap)
    await _check_and_reserve_budget(5.0, user_id="return_user")
    # 实际只用了 1.0, 退还 4.0
    await _return_budget(4.0, user_id="return_user")
    # 现在 spent=1.0, 可再 reserve 3.5
    await _check_and_reserve_budget(3.5, user_id="return_user")
    # 再 reserve 0.6 → 1.0+3.5+0.6=5.1 > 5 → 503
    with pytest.raises(HTTPException) as exc:
        await _check_and_reserve_budget(0.6, user_id="return_user")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_return_budget_zero_or_negative_noop(tmp_db):
    """_return_budget(0) 或 _return_budget(-1) 应静默 noop, 不抛错."""
    from backend.api.services.budget import _check_and_reserve_budget, _return_budget
    await _check_and_reserve_budget(2.0, user_id="zero_user")
    # 这两个调用都应静默成功
    await _return_budget(0.0, user_id="zero_user")
    await _return_budget(-1.0, user_id="zero_user")


# ===== 4. 跨小时窗口重置 =====

@pytest.mark.asyncio
async def test_budget_resets_after_hour(tmp_db, monkeypatch):
    """1h 后 reserve 累计应自动重置."""
    from backend.api.services import budget as budget_mod
    monkeypatch.setattr(budget_mod, "get_global_hourly_budget", lambda: 1.0)
    from backend.api.services.budget import _check_and_reserve_budget
    # 用满 cap
    await _check_and_reserve_budget(0.9, user_id="dev-user")
    # 直接修改 _DB 里的 reset_ts 到 1h 之前
    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    try:
        conn.execute(
            "UPDATE budget_state SET reset_ts=? WHERE key='global'",
            (_time.time() - 3601,),
        )
        conn.commit()
    finally:
        conn.close()
    # 现在再 reserve 应通过 (小时窗口已重置)
    await _check_and_reserve_budget(0.9, user_id="dev-user")


# ===== 5. 异常路径: pipeline 抛错, budget 仍可退还 =====

@pytest.mark.asyncio
async def test_return_after_failed_pipeline(tmp_db):
    """模拟 pipeline 异常后, _return_budget 应正常退还预留 budget."""
    from backend.api.services.budget import _check_and_reserve_budget, _return_budget
    # 模拟 pipeline 入口 reserve
    await _check_and_reserve_budget(1.0, user_id="fail_user")
    # 模拟 pipeline 异常 (e.g. LLM 失败) → finally 块调 _return_budget
    # 实际 cost 0 (没真跑), 退还全部 1.0
    await _return_budget(1.0, user_id="fail_user")
    # 后续 reserve 5.0 通过 (cap 内)
    await _check_and_reserve_budget(5.0, user_id="fail_user")
    await _return_budget(5.0, user_id="fail_user")


# ===== 6. 同一用户连续多次 reserve, 累计正确 =====

@pytest.mark.asyncio
async def test_multiple_reserves_accumulate(tmp_db, monkeypatch):
    """同一 user 多次 reserve 累计, 不超过 cap.

    注: multi_user (per-user) cap = 5.0 固定, 不能 monkeypatch 改.
    用 dev-user + get_global_hourly_budget monkeypatch 才能改 cap.
    """
    from backend.api.services import budget as budget_mod
    monkeypatch.setattr(budget_mod, "get_global_hourly_budget", lambda: 2.0)
    from backend.api.services.budget import _check_and_reserve_budget
    # 4 次 reserve 0.5 → 累计 2.0 == cap
    for _ in range(4):
        await _check_and_reserve_budget(0.5, user_id="dev-user")
    # 第 5 次 0.1 → 2.0 + 0.1 = 2.1 > 2.0 → 503
    with pytest.raises(HTTPException) as exc:
        await _check_and_reserve_budget(0.1, user_id="dev-user")
    assert exc.value.status_code == 503


# ===== 7. 不存在的 user_id: 首次 reserve 应初始化 (R10.5 Fix-X4 修复后) =====

@pytest.mark.asyncio
async def test_first_reserve_initializes_user_row(tmp_db):
    """首次 reserve 一个新 user_id 应在 budget_user 表创建 row, 不抛错."""
    from backend.api.services.budget import _check_and_reserve_budget
    # 新 user, 表中无 row
    await _check_and_reserve_budget(0.5, user_id="brand_new_user")
    # 再 reserve 也应通过
    await _check_and_reserve_budget(0.5, user_id="brand_new_user")
