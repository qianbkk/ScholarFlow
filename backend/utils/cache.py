"""
utils.cache — 查询结果 SQLite 缓存（避免重复跑流水线）
====================================================

- 同一 query + max_iterations + budget 在 TTL 内直接返回上次结果
- TTL 默认 24h，可由环境变量 CACHE_TTL_SECONDS 控制
- 整个缓存可通过环境变量 ENABLE_SEARCH_CACHE=false 关闭
- 缓存文件存放在 backend/.cache/search_cache.sqlite（已在 .gitignore 中）
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


def _init_db() -> None:
    with sqlite3.connect(_DB) as conn:
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
    with sqlite3.connect(_DB) as conn:
        row = conn.execute(
            "SELECT response_json, cost_usd, tokens, created_at "
            "FROM search_cache WHERE query_hash=?",
            (key,),
        ).fetchone()
        if not row:
            return None
        if time.time() - row[3] > ttl_seconds:
            return None  # expired
        return json.loads(row[0]), row[1], row[2]


def set_cached(
    query: str,
    max_iterations: int,
    budget: float,
    response: dict,
    cost_usd: float,
    tokens: int,
) -> None:
    """写入缓存（覆盖式 upsert）。"""
    if os.getenv("ENABLE_SEARCH_CACHE", "true").lower() != "true":
        return

    _init_db()
    key = cache_key(query, max_iterations, budget)
    with sqlite3.connect(_DB) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO search_cache VALUES (?, ?, ?, ?, ?, ?)",
            (
                key,
                query,
                json.dumps(response, ensure_ascii=False),
                cost_usd,
                tokens,
                time.time(),
            ),
        )
        conn.commit()
