"""
backend.utils.runtime_mode
==========================

R10.5.43: Runtime mode 共享化 (P0 multi-worker drift 修复).

历史:
- R10.5.20: in-memory dict `_runtime_mode_override`
  → 4-worker Gunicorn 部署下切 mock 只有 1/N 走 mock (P0 致命).
- R10.5.43: SQLite 共享表 + 进程内 1s 缓存
  → 跨 worker 一致, 切换后 ≤1s 全员生效
  → DB I/O 几乎不增加 (每 worker 每秒最多 1 次 read).
- R10.5.51 cleanup: 删 _RuntimeModeProxy dict-subclass 后向兼容 shim (76 行),
  所有调用点迁到显式 set_runtime_mode() / get_runtime_mode().

API:
- GET /api/v1/admin/runtime-mode → {mode: 'mock'|'real', source: 'env'|'runtime'}
- POST /api/v1/admin/runtime-mode body {mode: 'mock'|'real'} → 切模式

环境优先级 (R10.5.43 不变, 只换底层存储):
- runtime mode (SQLite 共享, 1s 进程内缓存)
- env LLM_MOCK || API_MOCK (config.py 启动时)
- 默认 False (走真实 API)

调用示例 (业务函数):
    from backend.utils.runtime_mode import is_runtime_mock
    if is_runtime_mock():
        return mock_data()
    else:
        return await real_api_call()

R10.5.25: RuntimeProfile enum (未动) + 集中状态表.
R10.5.43: 状态表从内存 dict 迁到 SQLite, 解决 P0 multi-worker drift.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from enum import Enum
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ===== R10.5.25: RuntimeProfile enum (未动) =====
class RuntimeProfile(str, Enum):
    """集中化的运行时 profile, 涵盖 5 开关最常见组合.

    实际 5 开关 (OPEN_MODE / LLM_MOCK / API_MOCK / ENVIRONMENT / runtime
    override) 仍独立工作, 此 enum 只在 startup 打印 + R11+ 强制互斥时
    才用作参考.

    Profile 定义:
      DEV_MOCK    — 本地开发, OPEN_MODE=true + LLM_MOCK=true + API_MOCK=true.
                    一键跑通, 不需任何 key.
      DEV_REAL    — 本地开发用真 LLM (有 MiniMax/Kimi/GLM key), OPEN_MODE=true.
                    演示/开发用, 鉴权不挡.
      OPEN_DEMO   — 多用户 demo, OPEN_MODE=false (强制 auth), LLM_MOCK=true.
                    演示部署: 用户能注册, 但 LLM 走 mock 节省成本.
      PRODUCTION  — 正式部署, OPEN_MODE=false + LLM_MOCK=false + API_MOCK=false.
                    全部走真 API, 鉴权强制, 配置完整.
    """
    DEV_MOCK = "dev_mock"
    DEV_REAL = "dev_real"
    OPEN_DEMO = "open_demo"
    PRODUCTION = "production"


def detect_runtime_profile() -> RuntimeProfile:
    """R10.5.25: 根据当前 5 开关推断 RuntimeProfile.

    推断规则 (按优先级):
      1. PRODUCTION: OPEN_MODE=false + LLM_MOCK=false + API_MOCK=false
      2. OPEN_DEMO:  OPEN_MODE=false + LLM_MOCK=true (允许 API_MOCK 任意)
      3. DEV_REAL:   OPEN_MODE=true  + LLM_MOCK=false
      4. DEV_MOCK:   OPEN_MODE=true  + LLM_MOCK=true (兜底)
    """
    from backend.config import LLM_MOCK, API_MOCK
    # 延迟 import 避免循环
    from backend.auth.dependencies import OPEN_MODE

    if not OPEN_MODE and not LLM_MOCK and not API_MOCK:
        return RuntimeProfile.PRODUCTION
    if not OPEN_MODE and LLM_MOCK:
        return RuntimeProfile.OPEN_DEMO
    if OPEN_MODE and not LLM_MOCK:
        return RuntimeProfile.DEV_REAL
    return RuntimeProfile.DEV_MOCK


# ===== R10.5.43: SQLite-backed shared state with 1s in-process cache =====
# Storage: SQLite table "runtime_mode_state" with single row (id=1)
# Why SQLite: 已有 WAL+busy_timeout+retry (cache.py), 零新依赖.
# Why 1s cache: multi-worker 部署下每 worker 每秒最多 1 次 DB read,
#              切换后 ≤1s 全员生效 (P0 致命漂移修复).
#              不需要进程间失效通知 — 1s 容忍窗已经够小.
# R10.5.51 cleanup (BACKLOG D-007): 删 dict-subclass proxy, 唯一公开 API:
#                          set_runtime_mode(mode) + get_runtime_mode().

_CACHE_TTL_SECONDS = 1.0
_runtime_mode_cache: dict = {
    "value": "auto",      # type: Literal["mock", "real", "auto"]
    "fetched_at": 0.0,     # monotonic time of last DB read
}
_RUNTIME_MODE_LOCK = threading.Lock()  # 保护 cache 读写 + 防御 DB 写竞争


def _read_from_db() -> str:
    """从 SQLite 读 runtime mode. 表无行时返 'auto' (默认 env 行为).

    R10.5.51 (/simplify): 删 _ensure_table(). cache.py _m_r10_5_43_runtime_mode_state
    migration 已在 _init_db_once() 跑过, runtime_mode_state 表已存在. 之前每
    次 cache 读写额外 CREATE IF NOT EXISTS 多花 2 个 DB round-trip (跟
    Plan 中 Reuse #3 + Efficiency #2 一致).
    """
    from backend.utils.cache import _init_db_once
    _init_db_once()
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        row = conn.execute(
            "SELECT mode FROM runtime_mode_state WHERE id=1"
        ).fetchone()
        if row is None:
            return "auto"
        val = row[0]
        if val not in ("mock", "real", "auto"):
            logger.warning(
                f"[runtime_mode] DB has invalid mode={val!r}, falling back to 'auto'"
            )
            return "auto"
        return val
    finally:
        conn.close()


def _write_to_db(mode: str) -> None:
    """写 runtime mode 到 SQLite. UPSERT 单行 (id=1).

    R10.5.51 (/simplify): 删 _ensure_table() 调 (migration 已建表).
    """
    from backend.utils.cache import _init_db_once
    _init_db_once()
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO runtime_mode_state (id, mode, updated_at) "
            "VALUES (1, ?, ?)",
            (mode, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def _invalidate_cache() -> None:
    """强制下次 get_runtime_mode() 立即读 DB. 跨进程不需要 — 1s TTL 自动失效."""
    with _RUNTIME_MODE_LOCK:
        _runtime_mode_cache["fetched_at"] = 0.0


def get_runtime_mode() -> Literal["mock", "real", "auto"]:
    """返回当前生效的 runtime 模式. 1s 进程内缓存 + SQLite 共享.

    跨 worker 一致性: 切换后 ≤1s 全员生效 (cache TTL 1s).

    R10.5.51 (/simplify): fast-path 无锁读 — 99% 调用在 1s TTL 内, 不需要
    拿 _RUNTIME_MODE_LOCK (Efficiency #1). 只在 stale 时拿锁串行化 DB 读.
    """
    # Fast-path: 99% 调用在 TTL 内, 无锁返回 (CPython GIL 保证 dict 读原子)
    if time.monotonic() - _runtime_mode_cache["fetched_at"] < _CACHE_TTL_SECONDS:
        return _runtime_mode_cache["value"]  # type: ignore[return-value]
    # Slow-path: stale, 拿锁串行化 DB 读
    with _RUNTIME_MODE_LOCK:
        now = time.monotonic()
        # Double-check: 可能在拿锁期间其他线程已经刷新
        if now - _runtime_mode_cache["fetched_at"] < _CACHE_TTL_SECONDS:
            return _runtime_mode_cache["value"]  # type: ignore[return-value]
        mode = _read_from_db()
        _runtime_mode_cache["value"] = mode
        _runtime_mode_cache["fetched_at"] = now
        return mode  # type: ignore[return-value]


def set_runtime_mode(mode: Literal["mock", "real", "auto"]) -> None:
    """前端调 admin API 设的. 'auto' = 恢复 env 行为.

    写 SQLite + 失效本进程缓存. 其他 worker 在 1s TTL 后看到新值.
    """
    _write_to_db(mode)
    # 失效本地缓存, 下次 get 立即读 DB
    _invalidate_cache()
    logger.info(f"[runtime_mode] override set to: {mode}")


def is_runtime_mock() -> bool:
    """业务函数查这个, 判断当前是否走 mock.

    优先级 (R10.5.43 不变, 只换底层存储):
      1. runtime mode (SQLite 共享, 1s 缓存)
      2. env LLM_MOCK || API_MOCK
      3. 默认 False (走真实 API)
    """
    mode = get_runtime_mode()
    if mode == "mock":
        return True
    if mode == "real":
        return False
    # auto: 走 env
    llm_mock = os.getenv("LLM_MOCK", "true").lower() in ("1", "true", "yes")
    api_mock = os.getenv("API_MOCK", "true").lower() in ("1", "true", "yes")
    return llm_mock or api_mock


# R10.5.51 cleanup (BACKLOG D-007): 删 _RuntimeModeProxy dict-subclass 后向兼容 shim.
# R10.5.43 立的, 当时为了不破坏老 conftest / 老测试代码用 `_runtime_mode_override["mode"] = "..."`
# 这种 dict 写法. 现在所有调用点 (3 处测试) 都迁到 set_runtime_mode() 显式 API.
# 删 76 行 shim + 模块级 _runtime_mode_override 实例.
