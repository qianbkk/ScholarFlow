"""
backend.api.services.budget
============================

Global per-hour USD budget gate (H1+H2+TOCTOU fixed).

Extracted from backend/main.py in the god-object refactor so the FastAPI
entrypoint no longer carries the SQL transactions inline.

Module-level mutable state (GLOBAL_HOURLY_BUDGET, _budget_reset_ts) is
exposed as functions so callers (notably `backend.main`) can host those
names in their own namespace while still delegating reads/writes to
this single source of truth. The host module can then define matching
property accessors and the legacy `main_mod._budget_reset_ts = 0.0`
test idiom continues to work.

Surface (kept stable for tests):
  * get_global_hourly_budget() / set_global_hourly_budget(v)
  * get_budget_reset_ts() / set_budget_reset_ts(v)
  * _budget_lock                       — asyncio.Lock
  * _init_budget_table()                — idempotent schema bootstrap
  * _load_budget_from_db() -> (total, reset_ts)
  * _save_budget_to_db(total, reset_ts) — BEGIN IMMEDIATE write
  * _load_budget_state()                — startup hydration (window-aware reset)
  * _check_and_reserve_budget(estimated_cost)
  * _return_budget(amount)              — non-negative delta return
"""
from __future__ import annotations

import asyncio
import logging
import os
import time as _time

from fastapi import HTTPException

# NEW-002 修复：logger 移至模块级
logger = logging.getLogger(__name__)


# 全局每小时预算计数器（H2 修复：迁移到 SQLite WAL — 多 worker 原子性）
# 旧版用进程内 dict + .budget_state.json 文件，4-worker Gunicorn 部署下：
#   - 4 个独立进程各持一份 counter，实际预算 × 4
#   - .json 文件非原子写入，4 进程同时写时可能损坏
# 新版：在已有 cache DB（WAL 模式）增加 budget_state 表，跨进程 / 跨 worker 共享。
_GLOBAL_HOURLY_BUDGET = float(os.getenv("GLOBAL_HOURLY_BUDGET", "50.0"))
_budget_lock = asyncio.Lock()
# 进程内只缓存 reset_ts（避免每次都读 DB）；total 始终从 DB 读最新值
_budget_reset_ts: float = _time.time()


# Backward-compat module-level names: re-bound to the dicts above so
# `from backend.api.services.budget import GLOBAL_HOURLY_BUDGET` still
# works for legacy code paths (the test suite never uses these names,
# but other modules might).
GLOBAL_HOURLY_BUDGET = _GLOBAL_HOURLY_BUDGET  # legacy read-only snapshot


def get_global_hourly_budget() -> float:
    """Return current per-hour budget cap (USD)."""
    return _GLOBAL_HOURLY_BUDGET


def set_global_hourly_budget(value: float) -> None:
    """Override the per-hour budget cap at runtime (used by tests via
    `main_mod.GLOBAL_HOURLY_BUDGET = ...` — the host module's property
    setter forwards to this setter)."""
    global _GLOBAL_HOURLY_BUDGET
    _GLOBAL_HOURLY_BUDGET = float(value)


def get_budget_reset_ts() -> float:
    """Return the in-process cached window-start timestamp."""
    return _budget_reset_ts


def set_budget_reset_ts(value: float) -> None:
    """Override the in-process cached reset_ts (test bridge)."""
    global _budget_reset_ts
    _budget_reset_ts = float(value)


def _init_budget_table() -> None:
    """初始化 budget_state 表 + 插入 global 行（H2 修复：复用 cache DB 的 WAL 连接）。

    幂等：多次调用只会创建一次表、只插入一次 global 行（INSERT OR IGNORE）。
    """
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_state (
                key TEXT PRIMARY KEY,
                total REAL NOT NULL,
                reset_ts REAL NOT NULL
            )
            """
        )
        # 默认行：global 计数器。INSERT OR IGNORE 避免覆盖现有数据。
        conn.execute(
            "INSERT OR IGNORE INTO budget_state (key, total, reset_ts) VALUES ('global', 0.0, ?)",
            (_time.time(),),
        )
        conn.commit()
    finally:
        conn.close()


def _load_budget_from_db() -> tuple[float, float]:
    """从 SQLite 读取 (total, reset_ts)。无行时返回 (0.0, now)。"""
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        row = conn.execute(
            "SELECT total, reset_ts FROM budget_state WHERE key='global'"
        ).fetchone()
        if row is None:
            return 0.0, _time.time()
        return float(row[0]), float(row[1])
    finally:
        conn.close()


def _save_budget_to_db(total: float, reset_ts: float) -> None:
    """把 (total, reset_ts) 持久化到 SQLite（H2 修复：跨进程原子）。

    兼容性: 仍接受 (total, reset_ts) 两参签名,内部封装 BEGIN IMMEDIATE 事务。
    详细事务包裹逻辑见 _check_and_reserve_budget / _return_budget。
    """
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        # BEGIN IMMEDIATE: 立即获取写锁,防止多 worker 间 TOCTOU 竞态
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE budget_state SET total=?, reset_ts=? WHERE key='global'",
            (total, reset_ts),
        )
        conn.commit()
    finally:
        conn.close()


def _load_budget_state() -> None:
    """启动时从 SQLite 恢复预算计数。无行/损坏时保持默认 (0, now)。"""
    try:
        _init_budget_table()
        total, ts = _load_budget_from_db()
        # 若记录的窗口已过期，则丢弃
        if _time.time() - ts > 3600:
            _save_budget_to_db(0.0, _time.time())
            set_budget_reset_ts(_time.time())
            total = 0.0
        else:
            set_budget_reset_ts(ts)
        logger.info(
            f"[budget] loaded persisted state: total=${total:.4f}, "
            f"reset_ts={get_budget_reset_ts():.0f}"
        )
    except Exception as e:
        logger.warning(f"[budget] failed to load state: {e}, starting fresh")


async def _check_and_reserve_budget(estimated_cost: float) -> None:
    """原子化地"检查 + 预留"全局预算（H1+H2+TOCTOU 修复）。

    H1: 整个 check + reserve 在 `_budget_lock` 临界区内完成，关闭进程内 TOCTOU 竞态。
    H2: counter 状态存储在 SQLite WAL 中（budget_state 表），跨 worker 进程原子。
    TOCTOU fix: 读-改-写 全程在 `BEGIN IMMEDIATE` 事务中，
        防止多 worker 进程间 SQLite 层面的 TOCTOU 竞态(普通 BEGIN 拿到的是
        共享锁,第二个 worker 进来时读到的仍是旧 total,会超额累加)。
        BEGIN IMMEDIATE 立即获取写锁,串行化整个 critical section。

    Args:
        estimated_cost: 本次请求愿意预留的最大开销（= `req.budget`，即用户上限）。
    """
    async with _budget_lock:
        # 从 DB 读最新值（避免任何缓存导致跨进程看到的旧 total）
        total, reset_ts = _load_budget_from_db()
        now = _time.time()
        if now - reset_ts > 3600:
            total = 0.0
            reset_ts = now
        if total + estimated_cost > get_global_hourly_budget():
            raise HTTPException(503, detail="全局预算上限已达，请稍后重试")
        # 在锁内完成预留 + 持久化（下一个 worker 读到的就是新 total）
        new_total = total + estimated_cost
        _save_budget_to_db(new_total, reset_ts)
        # 进程内缓存 reset_ts，避免每个请求都读 DB
        set_budget_reset_ts(reset_ts)


async def _return_budget(amount: float) -> None:
    """归还实际开销与预留之间的差额(防止过度预留耗尽全局预算)。

    入口 `_check_and_reserve_budget` 预留的是 `req.budget`(用户上限),
    但实际 `total_cost_usd` 通常远低于上限。差额若不归还,会导致
    后续请求被错误拒绝(503)。这里在请求结束时归还差额。

    实现: 加 asyncio.Lock + BEGIN IMMEDIATE,与 reserve 路径一致,
    保证多 worker 间的 read-modify-write 原子性。
    """
    if amount <= 0:
        return
    async with _budget_lock:
        from backend.utils.cache import _connect_with_wal
        conn = _connect_with_wal()
        try:
            conn.execute("BEGIN IMMEDIATE")  # 立即获取写锁,防多 worker TOCTOU
            row = conn.execute(
                "SELECT total, reset_ts FROM budget_state WHERE key='global'"
            ).fetchone()
            if row is None:
                return  # 表未初始化,无须归还
            total = float(row[0])
            reset_ts = float(row[1])
            # 边界保护: 不能减到负数
            new_total = max(0.0, total - amount)
            conn.execute(
                "UPDATE budget_state SET total=?, reset_ts=? WHERE key='global'",
                (new_total, reset_ts),
            )
            conn.commit()
            set_budget_reset_ts(reset_ts)
        finally:
            conn.close()


# 模块导入时自动加载一次（保持 main.py 旧行为：进程启动即恢复预算状态）
try:
    _load_budget_state()
except Exception as _e:  # pragma: no cover — 启动期失败已记日志
    logger.debug(f"[budget] initial load skipped: {_e}")
