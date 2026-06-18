"""
backend.utils.runtime_mode
==========================

R10.5.43: Runtime mode 共享化 (P0 multi-worker drift 修复).

历史:
- R10.5.20: in-memory dict `_runtime_mode_override`
  → 4-worker Gunicorn 部署下切 mock 只有 1/N 走 mock (P0 致命).
- R10.5.43: SQLite 共享表 + 进程内 1s 缓存
  → 跨 worker 一致, 切换后 ≤1s 全员生效
  → DB I/O 几乎不增加 (每 worker 每秒最多 1 次 read)
  → 旧 API 表面 (["mode"] = ..., get(...)) 通过 _RuntimeModeProxy dict-subclass
     100% 向后兼容, 不需要批量改测试代码.

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
# Why SQLite: 已有 WAL+busy_timeout+retry (cache.py:638-656), 零新依赖.
# Why 1s cache: multi-worker 部署下每 worker 每秒最多 1 次 DB read,
#              切换后 ≤1s 全员生效 (P0 致命漂移修复).
#              不需要进程间失效通知 — 1s 容忍窗已经够小.
# Why dict-subclass proxy: 向后兼容旧 `_runtime_mode_override["mode"] = ...`
#                          写法 (test_r10_5_39_multisource_search.py 等 7 处).
#                          proxy 拦截 mode 键, 透明转发到 SQLite.

_CACHE_TTL_SECONDS = 1.0
_runtime_mode_cache: dict = {
    "value": "auto",      # type: Literal["mock", "real", "auto"]
    "fetched_at": 0.0,     # monotonic time of last DB read
}
_RUNTIME_MODE_LOCK = threading.Lock()  # 保护 cache 读写 + 防御 DB 写竞争


def _ensure_table() -> None:
    """确保 runtime_mode_state 表存在. 防御性: cache.py 的 migration 已建表,
    这里再 CREATE IF NOT EXISTS 一次保证万无一失 (test fixture 切 DB path 时
    尤其需要). CREATE IF NOT EXISTS 是幂等的, 开销 <1ms.
    """
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_mode_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                mode TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _read_from_db() -> str:
    """从 SQLite 读 runtime mode. 表无行时返 'auto' (默认 env 行为)."""
    from backend.utils.cache import _init_db_once
    _init_db_once()
    _ensure_table()
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
    """写 runtime mode 到 SQLite. UPSERT 单行 (id=1)."""
    from backend.utils.cache import _init_db_once
    _init_db_once()
    _ensure_table()
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
    """
    with _RUNTIME_MODE_LOCK:
        now = time.monotonic()
        if now - _runtime_mode_cache["fetched_at"] < _CACHE_TTL_SECONDS:
            return _runtime_mode_cache["value"]  # type: ignore[return-value]
        # Cache miss / stale: 读 DB
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


# ===== R10.5.43: 向后兼容 _runtime_mode_override dict API =====
# 旧 API: rt._runtime_mode_override["mode"] = "mock"
# 旧 API: rt._runtime_mode_override.get("mode", "auto")
# 旧 API: if "mode" in rt._runtime_mode_override
# 新行为: 透明转发到 get_runtime_mode() / set_runtime_mode().
# 设计: dict subclass 拦截 'mode' 键, 其他键维持普通 dict 行为 (向后兼容).
#
# 重要: 这个 proxy 不允许被整个替换 — conftest 的
# `_runtime_mode_override = {"mode": "auto"}` 会破坏后续对 SQLite 的同步.
# 如果测试想"重置回 auto", 应该调 set_runtime_mode("auto"), 或者用
# proxy["mode"] = "auto" 透明写入 SQLite.

class _RuntimeModeProxy(dict):
    """dict-subclass proxy: 'mode' 键透明同步到 SQLite + 1s 缓存.

    R10.5.43: 保留旧 dict API 表面, 但状态权威源是 SQLite. 这样:
      - conftest / 老测试 写 `proxy["mode"] = "mock"` → 实际写 SQLite
      - is_runtime_mock() 通过 get_runtime_mode() 读 SQLite, 看到 mock
      - 跨 worker 一致性由 SQLite 保证, 不再是进程内 dict
    """

    def __init__(self) -> None:
        super().__init__()  # 内部 dict 不持有 mode (避免缓存不一致)
        # 注意: 不要 super().__setitem__("mode", "auto") — 走 set_runtime_mode

    def __getitem__(self, key: str) -> Any:
        if key == "mode":
            return get_runtime_mode()
        return super().__getitem__(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "mode":
            set_runtime_mode(value)  # type: ignore[arg-type]
            return
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        if key == "mode":
            set_runtime_mode("auto")
            return
        super().__delitem__(key)

    def __contains__(self, key: object) -> bool:
        if key == "mode":
            return True  # 永远有 'mode' 键 (默认 'auto')
        return super().__contains__(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "mode":
            return get_runtime_mode()
        return super().get(key, default)

    def pop(self, key: str, *args: Any) -> Any:
        if key == "mode":
            old = get_runtime_mode()
            set_runtime_mode("auto")
            return old
        return super().pop(key, *args)

    def update(self, *args: Any, **kwargs: Any) -> None:
        # 拦截 'mode' 键, 转发到 set_runtime_mode
        for d in args:
            if isinstance(d, dict) and "mode" in d:
                set_runtime_mode(d["mode"])  # type: ignore[arg-type]
        if "mode" in kwargs:
            set_runtime_mode(kwargs["mode"])  # type: ignore[arg-type]
        # 其他键走普通 dict.update
        clean_args = tuple(
            {k: v for k, v in d.items() if k != "mode"}
            for d in args if isinstance(d, dict)
        )
        clean_kwargs = {k: v for k, v in kwargs.items() if k != "mode"}
        if clean_args or clean_kwargs:
            super().update(*clean_args, **clean_kwargs)

    def clear(self) -> None:
        set_runtime_mode("auto")
        # 清掉其他键 (如果有)
        keys_to_remove = [k for k in self if k != "mode"]
        for k in keys_to_remove:
            super().__delitem__(k)

    def __repr__(self) -> str:
        return f"_RuntimeModeProxy(mode={get_runtime_mode()!r})"


# 模块级 proxy 实例 — 旧代码引用 _runtime_mode_override 自动走 proxy.
_runtime_mode_override = _RuntimeModeProxy()
