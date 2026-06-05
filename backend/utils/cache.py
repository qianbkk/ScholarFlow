"""
utils.cache — 查询结果 SQLite 缓存（避免重复跑流水线）
====================================================

- 同一 query + max_iterations + budget 在 TTL 内直接返回上次结果
- TTL 默认 24h，可由环境变量 CACHE_TTL_SECONDS 控制
- 整个缓存可通过环境变量 ENABLE_SEARCH_CACHE=false 关闭
- 缓存文件存放在 backend/.cache/search_cache.sqlite（已在 .gitignore 中）

并发安全（犀利评论 #10 修复）：
- 启用 WAL（Write-Ahead Logging）模式 — 支持多 reader + 1 writer 并发
- busy_timeout=5s — 等待锁释放而非立即抛 OperationalError
- OperationalError 时指数退避重试 — Gunicorn 多 worker 部署不再 500
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path


_CACHE_DIR = Path(__file__).parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)
_DB = _CACHE_DIR / "search_cache.sqlite"

# 并发安全：5s 等待锁超时（Gunicorn 多 worker 写同一文件时不会立即抛 lock 错）
_BUSY_TIMEOUT_MS = 5000
# OperationalError 重试上限（指数退避 50ms / 100ms / 200ms）
_MAX_RETRIES = 3


def _connect_with_wal() -> sqlite3.Connection:
    """建立支持 WAL 并发模式的 SQLite 连接。

    Returns:
        sqlite3.Connection — 每次返回新连接（避免跨线程持有同一连接）
    """
    conn = sqlite3.connect(str(_DB), timeout=_BUSY_TIMEOUT_MS / 1000)
    # WAL 模式是持久化的（写入数据库文件 header），只需设置一次
    # 但每次连接都执行 PRAGMA 是无害的（PRAGMA 是幂等的）
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    # WAL + 多进程下，建议 NORMAL 同步级别（性能 / 安全平衡点）
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_db() -> None:
    """初始化 cache 表 + WAL 模式。幂等。"""
    conn = _connect_with_wal()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_cache (
                query_hash TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                response_json TEXT NOT NULL,
                cost_usd REAL NOT NULL,
                tokens INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def cache_key(query: str, max_iterations: int, budget: float) -> str:
    return hashlib.sha256(
        f"{query.strip().lower()}|{max_iterations}|{budget}".encode()
    ).hexdigest()[:32]


def get_cached(
    query: str,
    max_iterations: int,
    budget: float,
    ttl_seconds: int | None = None,
):
    """读取缓存。

    Returns:
        None — 未命中 / 已过期 / 缓存被禁用
        (response_dict, cost_usd, tokens) — 命中
    """
    if os.getenv("ENABLE_SEARCH_CACHE", "true").lower() != "true":
        return None
    if ttl_seconds is None:
        ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "86400"))

    _init_db()
    key = cache_key(query, max_iterations, budget)
    for attempt in range(_MAX_RETRIES):
        try:
            conn = _connect_with_wal()
            try:
                row = conn.execute(
                    "SELECT response_json, cost_usd, tokens, created_at "
                    "FROM search_cache WHERE query_hash=?",
                    (key,),
                ).fetchone()
            finally:
                conn.close()
            if not row:
                return None
            if time.time() - row[3] > ttl_seconds:
                return None  # expired
            return json.loads(row[0]), row[1], row[2]
        except sqlite3.OperationalError as e:
            # 极端并发：busy_timeout 后仍未拿到锁，指数退避重试
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.05 * (2 ** attempt))
                continue
            # 重试耗尽：保守降级为未命中（不阻塞 /search）
            import logging
            logging.getLogger(__name__).warning(
                f"[cache] get_cached failed after {_MAX_RETRIES} retries: {e}"
            )
            return None
    return None


def set_cached(
    query: str,
    max_iterations: int,
    budget: float,
    response: dict,
    cost_usd: float,
    tokens: int,
) -> None:
    """写入缓存（覆盖式 upsert）。

    并发安全：
    - WAL 模式允许多 reader + 1 writer 并发
    - busy_timeout 等待锁释放
    - OperationalError 时指数退避重试
    """
    if os.getenv("ENABLE_SEARCH_CACHE", "true").lower() != "true":
        return

    _init_db()
    key = cache_key(query, max_iterations, budget)
    payload = (
        key,
        query,
        json.dumps(response, ensure_ascii=False),
        cost_usd,
        tokens,
        time.time(),
    )
    for attempt in range(_MAX_RETRIES):
        try:
            conn = _connect_with_wal()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO search_cache VALUES (?, ?, ?, ?, ?, ?)",
                    payload,
                )
                conn.commit()
            finally:
                conn.close()
            return
        except sqlite3.OperationalError as e:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.05 * (2 ** attempt))
                continue
            # 重试耗尽：非阻塞降级（log warning，缓存未写入但 /search 仍返回正确结果）
            import logging
            logging.getLogger(__name__).warning(
                f"[cache] set_cached failed after {_MAX_RETRIES} retries: {e}"
            )
            return
