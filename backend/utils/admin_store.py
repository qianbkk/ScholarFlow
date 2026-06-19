"""
backend.utils.admin_store — 持久化 admin 白名单 (R10.5.28)

CG.txt 审计 P0 #2 修复: 删 R10.5.25.1 "首个注册用户自动 admin" 后门, 改成
显式初始化 + 持久化. 三种配置方式, 优先级从高到低:

  1. 持久化 (admin.sqlite) — 跨 worker 共享, 走 CLI 管理:
     python -m backend.auth.admin add u_xxx
     python -m backend.auth.admin list
     python -m backend.auth.admin remove u_xxx
  2. 环境变量 ADMIN_USER_IDS=uid1,uid2 — 适合 Docker 镜像 / K8s Secret
  3. (无后门) 没配就没 admin, 任何 admin/* 端点 POST 都 403

SQLite 表 schema:
  CREATE TABLE admins (
      user_id TEXT PRIMARY KEY,
      created_at REAL NOT NULL,
      note TEXT
  );

存储位置: backend/.cache/admin.sqlite (跟 auth/budget/cache 表分文件避免争锁).

R10.5.49 (P2 defense-in-depth): 加 _WRITE_LOCK 保护多线程 commit.
旧版 check_same_thread=False 共享 connection, 多线程同时 add_admin
导致 'cannot commit - no transaction is active' 错 (connection.transaction
state 跨线程污染). 修: threading.Lock 串行化所有写操作. 读操作不锁
(SQLite WAL 支持并发读).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_DIR = Path(__file__).resolve().parent.parent / ".cache"
_DB_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DB_DIR / "admin.sqlite"

_conn: sqlite3.Connection | None = None
_WRITE_LOCK = threading.Lock()  # 保护所有 add / remove 写


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        # R10.5.49 (P2 defense-in-depth): 加 busy_timeout, 跟 cache.py 对齐.
        # 旧版只设 journal_mode=WAL, 缺 busy_timeout → 4 worker 部署下
        # 同时调 add/remove_admin 撞写锁立即 OperationalError("database is locked"),
        # CLI /admin add 命令偶发失败. 5s busy_timeout 跟 cache.py 一致,
        # 写锁等待 < 5s 内通常能拿到, 体验一致.
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id    TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                note       TEXT
            )
            """
        )
        _conn.commit()
    return _conn


def list_admin_user_ids() -> frozenset[str]:
    """返 admin 集合 (持久化层). 跟 ADMIN_USER_IDS env 合并用."""
    try:
        rows = _get_conn().execute("SELECT user_id FROM admins").fetchall()
        return frozenset(r[0] for r in rows)
    except Exception as e:
        logger.warning(f"[admin_store] list_admin_user_ids failed: {e}")
        return frozenset()


def add_admin(user_id: str, note: str = "") -> bool:
    """CLI 入口: 加 user_id 进 admin 白名单. 返 True=新加, False=已存在.

    R10.5.49 (P2): _WRITE_LOCK 保护 commit. 多线程同时 add 串行化,
    避免 'cannot commit - no transaction is active' 错.
    """
    import time
    with _WRITE_LOCK:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO admins (user_id, created_at, note) VALUES (?, ?, ?)",
                (user_id, time.time(), note),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"[admin_store] add_admin failed: {e}")
            return False


def remove_admin(user_id: str) -> bool:
    """CLI 入口: 移 user_id 出 admin 白名单.

    R10.5.49 (P2): _WRITE_LOCK 保护 commit. 跟 add_admin 共享同一把锁.
    """
    with _WRITE_LOCK:
        conn = _get_conn()
        try:
            cur = conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            logger.error(f"[admin_store] remove_admin failed: {e}")
            return False


def clear_runtime_admin_users() -> None:
    """测试用: 清空 admins 表."""
    with _WRITE_LOCK:
        conn = _get_conn()
        try:
            conn.execute("DELETE FROM admins")
            conn.commit()
        except Exception as e:
            logger.warning(f"[admin_store] clear failed: {e}")
