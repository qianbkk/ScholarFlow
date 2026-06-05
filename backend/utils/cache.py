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

H4 修复：async 变体（get_cached_async / set_cached_async）：
- 旧实现的 time.sleep(0.05 * 2**attempt) 在 async 调用栈中会阻塞事件循环
- 新实现的 asyncio.sleep + asyncio.to_thread 把 SQLite I/O 和退避 sleep 都 offload
"""
from __future__ import annotations

import asyncio
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
    """初始化 cache 表 + WAL 模式。幂等。

    H8 修复：旧 schema 在 search_cache 表里存了完整 query 文本，
    配合 query_hash 暴露了"哪些 query 被搜过 + 返回了哪些结果"。
    Cache 文件一旦泄露（read 权限错误、备份文件、CI artifact），
    攻击者直接拿到所有用户查询历史和报告内容。新 schema 只存
    `query_hash`（不可逆 SHA-256 摘要）+ 响应。
    """
    conn = _connect_with_wal()
    try:
        # ===== 检测旧 schema 并就地迁移 =====
        # 三种情况：
        #   a) 表不存在         → 直接 CREATE 新表
        #   b) 表存在但带 query 列 → 迁移：建新表 + 拷数据 + DROP + RENAME
        #   c) 表存在且无 query 列 → 什么都不做（幂等）
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_cache'"
        )
        table_exists = cur.fetchone() is not None

        if table_exists:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(search_cache)").fetchall()
            }
            if "query" in cols:
                # 旧表带 query 列：CREATE 新表 → 拷无 query 数据 → DROP → RENAME
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS search_cache_new (
                        query_hash TEXT PRIMARY KEY,
                        response_json TEXT NOT NULL,
                        cost_usd REAL NOT NULL,
                        tokens INTEGER NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO search_cache_new
                        (query_hash, response_json, cost_usd, tokens, created_at)
                    SELECT query_hash, response_json, cost_usd, tokens, created_at
                    FROM search_cache
                    """
                )
                conn.execute("DROP TABLE search_cache")
                conn.execute("ALTER TABLE search_cache_new RENAME TO search_cache")
                # SQLite DROP TABLE 不会实际擦除数据页 — query 文本仍残留在
                # 释放的 page 中直到 VACUUM 重建整个文件。这里必须 VACUUM
                # 才能让原始 query 文本真正从磁盘文件中消失 (H8 隐私目标)。
                # 注意: VACUUM 不能在事务内执行,先 commit 再调。
                conn.commit()
                conn.execute("VACUUM")
                import logging
                logging.getLogger(__name__).info(
                    "[cache] H8 migration: dropped `query` column + VACUUM "
                    "to scrub original query text from disk (privacy hardening)"
                )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
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


# ===== H4 修复：async 同步辅助函数（offload 阻塞 I/O 到线程） =====

def _get_cached_sync(key: str, ttl_seconds: int):
    """同步 SQLite cache 读。被 get_cached_async 通过 asyncio.to_thread 调用。"""
    _init_db()
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
        return None
    return json.loads(row[0]), row[1], row[2]


def _set_cached_sync(key: str, response: dict, cost_usd: float, tokens: int) -> None:
    """同步 SQLite cache 写。被 set_cached_async 通过 asyncio.to_thread 调用。

    H8 修复：不再接受 `query` 参数 — query 文本不落盘，cache 里只存 hash。
    """
    _init_db()
    payload = (
        key,
        json.dumps(response, ensure_ascii=False),
        cost_usd,
        tokens,
        time.time(),
    )
    conn = _connect_with_wal()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO search_cache VALUES (?, ?, ?, ?, ?)",
            payload,
        )
        conn.commit()
    finally:
        conn.close()


def get_cached(
    query: str,
    max_iterations: int,
    budget: float,
    ttl_seconds: int | None = None,
):
    """读取缓存（同步版本 — 保留向后兼容，测试和遗留同步调用方使用）。

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
    """写入缓存（同步版本 — 保留向后兼容）。

    并发安全：
    - WAL 模式允许多 reader + 1 writer 并发
    - busy_timeout 等待锁释放
    - OperationalError 时指数退避重试
    """
    if os.getenv("ENABLE_SEARCH_CACHE", "true").lower() != "true":
        return

    _init_db()
    key = cache_key(query, max_iterations, budget)
    # H8 修复：payload 不再含 query 文本 — query_hash 已是不可逆 SHA-256。
    payload = (
        key,
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
                    "INSERT OR REPLACE INTO search_cache VALUES (?, ?, ?, ?, ?)",
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


# ===== H4 修复：async 变体 — 不阻塞事件循环 =====

async def get_cached_async(
    query: str,
    max_iterations: int,
    budget: float,
    ttl_seconds: int | None = None,
):
    """async 版本：把 SQLite I/O 放到线程池，retry 退避用 asyncio.sleep。

    旧版 get_cached 在 async 调用栈中会因 time.sleep 阻塞事件循环，最长 350ms。
    改用 asyncio.to_thread + asyncio.sleep 后，重试期间事件循环可继续处理其他请求。
    """
    if os.getenv("ENABLE_SEARCH_CACHE", "true").lower() != "true":
        return None
    if ttl_seconds is None:
        ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "86400"))

    key = cache_key(query, max_iterations, budget)
    for attempt in range(_MAX_RETRIES):
        try:
            return await asyncio.to_thread(_get_cached_sync, key, ttl_seconds)
        except sqlite3.OperationalError as e:
            if attempt < _MAX_RETRIES - 1:
                # 用 asyncio.sleep 让出事件循环（不阻塞）
                await asyncio.sleep(0.05 * (2 ** attempt))
                continue
            import logging
            logging.getLogger(__name__).warning(
                f"[cache] get_cached_async failed after {_MAX_RETRIES} retries: {e}"
            )
            return None
    return None


async def set_cached_async(
    query: str,
    max_iterations: int,
    budget: float,
    response: dict,
    cost_usd: float,
    tokens: int,
) -> None:
    """async 版本：把 SQLite I/O 放到线程池，retry 退避用 asyncio.sleep。

    旧版 set_cached 在 async 调用栈中会因 time.sleep 阻塞事件循环，最长 350ms。

    H8 修复：query 文本不再传递给 _set_cached_sync（只 cache_key 用来算 hash）。
    """
    if os.getenv("ENABLE_SEARCH_CACHE", "true").lower() != "true":
        return
    key = cache_key(query, max_iterations, budget)
    for attempt in range(_MAX_RETRIES):
        try:
            await asyncio.to_thread(
                _set_cached_sync, key, response, cost_usd, tokens,
            )
            return
        except sqlite3.OperationalError as e:
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(0.05 * (2 ** attempt))
                continue
            import logging
            logging.getLogger(__name__).warning(
                f"[cache] set_cached_async failed after {_MAX_RETRIES} retries: {e}"
            )
            return
