"""backend.utils.session_store
=============================

R10.5.30 (D3 P0-1): HttpOnly cookie session store.

替代 R10.5.28 sessionStorage / X-API-Key 模式, 真正修 CG.txt §1 P1 #4
(长期 API Key 在前端/扩展易被 XSS 偷).

设计:
  - 登录成功 → 后端生成 session_id (32 字节 base64url), 存 SQLite (跨 worker 共享)
  - 后端 Set-Cookie: session_id=...; HttpOnly; Secure; SameSite=Strict;
    Path=/; Max-Age=86400 (24 小时)
  - 前端 fetch credentials: 'include', 不再读/写任何 cookie/localStorage/sessionStorage
  - /auth/logout 删除 session 行, Set-Cookie 立即过期
  - CSRF: 写操作 (POST/PUT/DELETE) 必须带 X-CSRF-Token 头 (cookie 之外独立
    路径, 跟 session_id 在双重提交 cookie 模式)

Table: sessions (session_id PK, user_id, expires_at, created_at, csrf_token,
                last_seen_at, ip_address)
"""
from __future__ import annotations

import base64
import logging
import secrets
import time
from typing import Optional

from backend.utils.cache import _connect_with_wal

logger = logging.getLogger(__name__)

_SESSION_TTL_SEC = 86400  # 24 小时
_CSRF_HEADER = "X-CSRF-Token"
_SESSION_COOKIE = "sf_session_id"
_CSRF_COOKIE = "sf_csrf_token"


def _ensure_sessions_table() -> None:
    """首次访问时建表 + 索引."""
    conn = _connect_with_wal("auth")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                csrf_token TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                ip_address TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")
        conn.commit()
    finally:
        conn.close()


def _generate_session_id() -> str:
    """32 字节 base64url, 43 字符. 跟 api_key 格式类似但前缀 'ss_' 区分."""
    return "ss_" + secrets.token_urlsafe(32)


def _generate_csrf_token() -> str:
    """32 字节 base64url, 跟 session_id 独立."""
    return secrets.token_urlsafe(32)


def create_session(user_id: str, ip_address: Optional[str] = None) -> dict:
    """创建新 session, 返 (session_id, csrf_token, expires_at)."""
    _ensure_sessions_table()
    session_id = _generate_session_id()
    csrf_token = _generate_csrf_token()
    now = time.time()
    expires = now + _SESSION_TTL_SEC
    conn = _connect_with_wal("auth")
    try:
        conn.execute(
            """
            INSERT INTO sessions (session_id, user_id, csrf_token, expires_at, created_at, last_seen_at, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, csrf_token, expires, now, now, ip_address),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "session_id": session_id,
        "csrf_token": csrf_token,
        "expires_at": expires,
        "ttl_sec": _SESSION_TTL_SEC,
    }


def resolve_session(session_id: str) -> Optional[dict]:
    """校验 session_id, 返 (user_id, csrf_token) 或 None (失效/过期/不存在).

    跟 _resolve_stream_token 同模型 (SQLite 跨 worker 共享, in-memory 无效).
    """
    if not session_id:
        return None
    _ensure_sessions_table()
    conn = _connect_with_wal("auth")
    try:
        row = conn.execute(
            "SELECT user_id, csrf_token, expires_at FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    user_id, csrf_token, expires = row
    if time.time() > expires:
        return None
    return {"user_id": user_id, "csrf_token": csrf_token}


def touch_session(session_id: str) -> None:
    """更新 last_seen_at (滑动过期, R11+ 完善). R10.5.30 暂只更新 timestamp."""
    if not session_id:
        return
    conn = _connect_with_wal("auth")
    try:
        conn.execute(
            "UPDATE sessions SET last_seen_at=? WHERE session_id=?",
            (time.time(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_session(session_id: str) -> None:
    """登出: 删 session 行."""
    if not session_id:
        return
    conn = _connect_with_wal("auth")
    try:
        conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def gc_sessions() -> int:
    """清理过期 session, 返删除行数."""
    _ensure_sessions_table()
    conn = _connect_with_wal("auth")
    try:
        cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
