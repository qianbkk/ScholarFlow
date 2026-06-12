"""backend.auth — API Key 认证 + 用户管理 (R10.5 Fix-P0-B)

为高校私有化部署提供多用户 + budget 隔离:
  - /auth/register: 邮箱 + 显示名 → 生成 API Key
  - /auth/login:    email → 拿已有 key (无密码, 学术工具场景信任少)
  - get_current_user: 校验 X-API-Key header, 返 User 对象
  - OPEN_MODE=true 时跳过校验, 返 synthetic "dev-user"

API Key 设计:
  - 32 字节随机 (base64url 编码, ~43 字符)
  - 仅存 sha256 摘要 (不存明文)
  - 用户注册后只能看到一次明文, 丢失需重新登录/重置
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException

from backend.utils.cache import _connect_with_wal

logger = logging.getLogger(__name__)


# ===== 配置 =====
OPEN_MODE = os.getenv("OPEN_MODE", "").lower() in ("1", "true", "yes")
# OPEN_MODE=true 时所有请求共享 'dev-user' 虚拟账户, 行为跟 R10.5 之前一致.
# 生产部署必设 OPEN_MODE=false 强制认证.


# ===== User 数据类 =====
@dataclass
class User:
    user_id: str
    display_name: str
    created_at: float
    # is_dev_user: OPEN_MODE 模式下的合成用户, 不存在数据库行
    is_dev_user: bool = False


# ===== 工具 =====
def _hash_key(raw: str) -> str:
    """API Key 摘要 (sha256). 数据库只存摘要, 不可逆."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_key() -> str:
    """生成新的 API Key: 'sf_' + 32 字节 base64url = 35 字符可识别前缀."""
    return "sf_" + secrets.token_urlsafe(32)


# ===== 用户 CRUD =====
def _register_user(display_name: str = "") -> tuple[User, str]:
    """创建新用户, 返 (User 对象, 生成的明文 key).

    明文 key 仅在创建时返回一次, 之后只存 hash. 丢失需重置.
    """
    raw_key = _generate_key()
    key_hash = _hash_key(raw_key)
    user_id = "u_" + uuid.uuid4().hex[:12]
    now = time.time()

    conn = _connect_with_wal("auth")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO users (user_id, api_key_hash, display_name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, key_hash, display_name, now),
        )
        conn.execute(
            "INSERT INTO budget_user (user_id, spent_usd, reserved_usd, "
            "last_reset_hour, updated_at) VALUES (?, 0.0, 0.0, 0, ?)",
            (user_id, now),
        )
        conn.commit()
    finally:
        conn.close()

    return User(
        user_id=user_id,
        display_name=display_name,
        created_at=now,
        is_dev_user=False,
    ), raw_key


def _lookup_user_by_key(raw_key: str) -> Optional[User]:
    """通过明文 key 查 user, 返 None 表示无效."""
    if not raw_key:
        return None
    key_hash = _hash_key(raw_key)
    conn = _connect_with_wal("auth")
    try:
        row = conn.execute(
            "SELECT user_id, display_name, created_at FROM users "
            "WHERE api_key_hash = ?",
            (key_hash,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return User(
        user_id=row[0],
        display_name=row[1],
        created_at=row[2],
        is_dev_user=False,
    )


# ===== FastAPI 依赖 =====
async def get_current_user(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> User:
    """FastAPI dependency: 校验 X-API-Key 头, 返 User.

    OPEN_MODE=true 时: 跳过校验, 返合成 'dev-user' (无 DB 写入).
    OPEN_MODE=false 时: 校验 key, 无效或缺失返 401.
    """
    if OPEN_MODE:
        # 跳过认证, 返合成用户.  budget 走 'dev-user' 单账户, 行为跟旧版兼容.
        return User(
            user_id="dev-user",
            display_name="Open Mode Dev",
            created_at=0.0,
            is_dev_user=True,
        )

    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="缺少 X-API-Key header. 请先 /auth/register 或 /auth/login 拿 key, "
                   "或在 .env 设 OPEN_MODE=true (仅本地开发)",
        )
    user = _lookup_user_by_key(x_api_key)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="API Key 无效或已撤销",
        )
    return user


# ===== 业务逻辑 (auth 服务本身) =====
def issue_key_for_email(email: str, display_name: str = "") -> Optional[str]:
    """若 email 已注册, 返已有 key (重新登录); 否则注册新用户.

    注: 这是 'login' 端点, 实际是 '拿 key' 流程.  学术工具信任模型下
    email 即可证明身份 (高校邮箱 + 知网账号体系是常见模式).
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return None

    # 已注册? 返已有 key
    conn = _connect_with_wal("auth")
    try:
        # R10.5.17: user_id 派生改用 backend.utils.user_id.hash_user_id 单源.
        # 之前 5 处 inline (3 在 auth/dependencies.py, 2 在 routes/auth.py) 用
        # 3 种 normalize 策略 (无 lower / lower / lower+strip), SIEM 关联查询
        # (audit log 跟 auth DB 互查) 会因为大小写算出不同 user_id.
        from backend.utils.user_id import hash_user_id
        row = conn.execute(
            "SELECT api_key_hash FROM users WHERE user_id = ?",
            (hash_user_id(email),),
        ).fetchone()
    finally:
        conn.close()
    if row:
        # 已有用户 — 重新生成 key (旧 key 立即失效), 跟 R10.5 之前缓存架构类似
        new_key = _generate_key()
        new_hash = _hash_key(new_key)
        conn = _connect_with_wal("auth")
        try:
            # R10.5.17: 同上, 用 hash_user_id 单源
            from backend.utils.user_id import hash_user_id
            conn.execute(
                "UPDATE users SET api_key_hash = ? WHERE user_id = ?",
                (new_hash, hash_user_id(email)),
            )
            conn.commit()
        finally:
            conn.close()
        return new_key

    # 新用户: 用 email hash 作 user_id (确定性, 同 email 重新 login 拿到同 user)
    # R10.5.17: 用 backend.utils.user_id.hash_user_id 单源 (跟 audit log 一致).
    from backend.utils.user_id import hash_user_id
    user_id = hash_user_id(email)
    raw_key = _generate_key()
    key_hash = _hash_key(raw_key)
    now = time.time()
    conn = _connect_with_wal("auth")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, api_key_hash, display_name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, key_hash, display_name or email, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO budget_user (user_id, spent_usd, reserved_usd, "
            "last_reset_hour, updated_at) VALUES (?, 0.0, 0.0, 0, ?)",
            (user_id, now),
        )
        conn.commit()
    finally:
        conn.close()
    return raw_key
