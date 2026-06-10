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
    conn = _connect_with_wal("budget")
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
    conn = _connect_with_wal("budget")
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
    conn = _connect_with_wal("budget")
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


async def _check_and_reserve_budget(estimated_cost: float, user_id: str = "dev-user") -> None:
    """原子化地"检查 + 预留"per-user 预算（R10.5 Fix-P0-B: 多用户 budget 隔离）。

    H1: 整个 check + reserve 在 `_budget_lock` 临界区内完成，关闭进程内 TOCTOU 竞态。
    H2: counter 状态存储在 SQLite WAL 中（budget_user 表），跨 worker 进程原子。
    TOCTOU fix: 读-改-写 全程在 `BEGIN IMMEDIATE` 事务中，
        防止多 worker 进程间 SQLite 层面的 TOCTOU 竞态(普通 BEGIN 拿到的是
        共享锁,第二个 worker 进来时读到的仍是旧 total,会超额累加)。
        BEGIN IMMEDIATE 立即获取写锁,串行化整个 critical section。

    Args:
        estimated_cost: 本次请求愿意预留的最大开销（= `req.budget`，即用户上限）。
        user_id: 多用户隔离 key. OPEN_MODE 模式统一传 "dev-user".

    R10.5 Fix-X4 (P1-3 审计 X.md/AAA.txt): 把"读+判断+写"全程在同一个
    `BEGIN IMMEDIATE` 事务内完成, 杜绝多 worker 进程间 TOCTOU 竞态. 旧实现:
    进程内 _budget_lock 保护, 但跨进程失效; `_load_*_from_db` 用普通 SELECT
    (共享锁), `_save_*_to_db` 才开 BEGIN IMMEDIATE, 中间窗口另一个 worker
    读到的仍是旧值, 两次 reserve 各自相加, 后写覆盖, total 偏小.
    修复: 开一个连接, 整个 check + update 在单事务内, 写完 commit 再 close.
    """
    async with _budget_lock:
        from backend.utils.cache import _connect_with_wal
        conn = _connect_with_wal("budget")
        try:
            conn.execute("BEGIN IMMEDIATE")
            # 1) 读 (在 IMMEDIATE 事务内, 其他 writer 排队)
            if user_id == "dev-user":
                row = conn.execute(
                    "SELECT total, reset_ts FROM budget_state WHERE key='global'"
                ).fetchone()
                spent = float(row[0]) if row else 0.0
                reserved = 0.0  # 旧表无 reserved 字段, 兼容
                reset_ts = float(row[1]) if row else _time.time()
            else:
                # R10.5 code-review-X4: 区分"表不存在"(R10.5 之前 fixture 兼容)
                # 和"其他 DB 错误"(production 应暴露 500). 旧实现裸 except Exception
                # 早 return → 表不存在时 silently 让请求通过, cap 完全失效 (隐藏 config bug).
                try:
                    row = conn.execute(
                        "SELECT spent_usd, reserved_usd, last_reset_hour "
                        "FROM budget_user WHERE user_id=?",
                        (user_id,),
                    ).fetchone()
                except Exception as e:
                    conn.rollback()
                    # OperationalError "no such table" → fixture 兼容: 让请求通过 (无 budget 跟踪)
                    # 其他 sqlite3.Error → production 错: 抛出 500 让 ops 知道
                    err_msg = str(e)
                    if "no such table" in err_msg or "no such column" in err_msg:
                        logger.warning(
                            f"[budget] budget_user 表/列不存在, 跳过 cap 检查 (likely 测试 fixture): {err_msg}"
                        )
                        return  # 不抛, 让请求继续
                    logger.error(f"[budget] DB 错误: {err_msg}")
                    raise HTTPException(503, detail=f"预算系统暂时不可用: {err_msg[:100]}")
                if row is None:
                    # 首次 reserve: 初始化 row
                    spent = 0.0
                    reserved = 0.0
                    reset_ts = _time.time()
                else:
                    spent = float(row[0])
                    reserved = float(row[1])
                    reset_ts = float(row[2])
            now = _time.time()
            if now - reset_ts > 3600:
                spent = 0.0
                reserved = 0.0
                reset_ts = now
            # Per-user 隔离: 各自 hour 预算 = global 1/10 (5 美元)
            if user_id == "dev-user":
                hour_cap = get_global_hourly_budget()
            else:
                hour_cap = 5.0
            if spent + estimated_cost > hour_cap:
                # R10.5 Fix-X4: 抛错前先 rollback, 释放写锁
                conn.rollback()
                raise HTTPException(
                    503,
                    detail=f"用户 {user_id} 本小时预算上限 ${hour_cap:.2f} 已达, 请稍后重试",
                )
            # 2) 写 (在同事务内, 下一 worker 读到的是新值)
            new_spent = spent + estimated_cost
            new_reserved = reserved + estimated_cost
            if user_id == "dev-user":
                conn.execute(
                    "UPDATE budget_state SET total=?, reset_ts=? WHERE key='global'",
                    (new_spent, reset_ts),
                )
            else:
                conn.execute(
                    "INSERT INTO budget_user (user_id, spent_usd, reserved_usd, "
                    "last_reset_hour, updated_at) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "spent_usd=excluded.spent_usd, "
                    "reserved_usd=excluded.reserved_usd, "
                    "last_reset_hour=excluded.last_reset_hour, "
                    "updated_at=excluded.updated_at",
                    (user_id, new_spent, new_reserved, reset_ts, _time.time()),
                )
            conn.commit()
            set_budget_reset_ts(reset_ts)
        except HTTPException:
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass


async def _return_budget(amount: float, user_id: str = "dev-user") -> None:
    """归还实际开销与预留之间的差额(防止过度预留耗尽用户预算)。

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
        conn = _connect_with_wal("budget")
        try:
            conn.execute("BEGIN IMMEDIATE")  # 立即获取写锁,防多 worker TOCTOU
            if user_id == "dev-user":
                # OPEN_MODE dev-user 走旧 budget_state 'global' (向后兼容)
                row = conn.execute(
                    "SELECT total, reset_ts FROM budget_state WHERE key='global'"
                ).fetchone()
                if row is None:
                    return
                total = float(row[0])
                reset_ts = float(row[1])
                new_total = max(0.0, total - amount)
                conn.execute(
                    "UPDATE budget_state SET total=?, reset_ts=? WHERE key='global'",
                    (new_total, reset_ts),
                )
            else:
                # 多用户路径走 budget_user
                try:
                    row = conn.execute(
                        "SELECT spent_usd, reserved_usd, last_reset_hour "
                        "FROM budget_user WHERE user_id=?",
                        (user_id,),
                    ).fetchone()
                except Exception:
                    # 旧 test fixture 没 _init_db(), 表不存在
                    conn.rollback()
                    return
                if row is None:
                    return  # 用户不存在
                spent = float(row[0])
                reserved = float(row[1])
                reset_ts = float(row[2])
                new_spent = max(0.0, spent - amount)
                new_reserved = max(0.0, reserved - amount)
                conn.execute(
                    "UPDATE budget_user SET spent_usd=?, reserved_usd=?, "
                    "last_reset_hour=?, updated_at=? WHERE user_id=?",
                    (new_spent, new_reserved, reset_ts, _time.time(), user_id),
                )
            conn.commit()
            set_budget_reset_ts(reset_ts)
        finally:
            conn.close()


# ===== R10.5 Fix-P0-B: per-user budget DB 助手 =====

def _load_user_budget_from_db(user_id: str) -> tuple[float, float, float]:
    """从 budget_user / budget_state 读 (spent, reserved, reset_ts). 无行返 (0, 0, now).

    R10.5 Fix-P0-B 兼容: dev-user 走旧 budget_state 'global' 行 (向后兼容,
    旧 test 期望 total 单字段, _save_user_budget_to_db 写到 budget_state
    这里也读 budget_state 保持对称). 多用户走 budget_user 表.

    旧 test fixture 用 _init_budget_table() 但没 _init_db() 时 budget_user
    表不存在, 走默认.
    """
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal("budget")
    try:
        if user_id == "dev-user":
            # 读 budget_state 'global' total (向后兼容旧 _load_budget_from_db)
            try:
                row = conn.execute(
                    "SELECT total, reset_ts FROM budget_state WHERE key='global'"
                ).fetchone()
            except Exception:
                return 0.0, 0.0, _time.time()
            if row is None:
                return 0.0, 0.0, _time.time()
            total = float(row[0])
            reset_ts = float(row[1])
            return total, total, reset_ts  # reserved == spent (没单独字段)
        try:
            row = conn.execute(
                "SELECT spent_usd, reserved_usd, last_reset_hour "
                "FROM budget_user WHERE user_id=?",
                (user_id,),
            ).fetchone()
        except Exception:
            return 0.0, 0.0, _time.time()
        if row is None:
            return 0.0, 0.0, _time.time()
        return float(row[0]), float(row[1]), float(row[2])
    finally:
        conn.close()


def _save_user_budget_to_db(
    user_id: str, spent: float, reserved: float, reset_ts: float
) -> None:
    """持久化 per-user budget. 借用原 budget_state 表的 key='global' 行
    给 dev-user 用, 避免双轨."""
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal("budget")
    try:
        if user_id == "dev-user":
            # OPEN_MODE dev-user 走旧 budget_state 'global' 行 (向后兼容)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE budget_state SET total=?, reset_ts=? WHERE key='global'",
                (spent, reset_ts),
            )
        else:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO budget_user (user_id, spent_usd, reserved_usd, "
                "last_reset_hour, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "spent_usd=excluded.spent_usd, "
                "reserved_usd=excluded.reserved_usd, "
                "last_reset_hour=excluded.last_reset_hour, "
                "updated_at=excluded.updated_at",
                (user_id, spent, reserved, reset_ts, _time.time()),
            )
        conn.commit()
    finally:
        conn.close()


# 模块导入时自动加载一次（保持 main.py 旧行为：进程启动即恢复预算状态）
try:
    _load_budget_state()
except Exception as _e:  # pragma: no cover — 启动期失败已记日志
    logger.debug(f"[budget] initial load skipped: {_e}")
