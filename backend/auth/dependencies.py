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
# R10.5.19 (Q.txt #1): 默认值仍为 false (生产安全), 但 README 写错.
# 修正: 代码默认 = false (强制认证), 本地开发请在 .env 设 OPEN_MODE=true.
# lifespan 启动时会检测, OPEN_MODE=true 时打印醒目 [SECURITY] 警告.
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


# ===== R10.5.21 修复 (J.txt + K.txt 审计 #1) =====
# Admin 端点保护: admin/runtime-mode 切 mock/real 影响全系统 LLM 花费,
# 默认必须 fail-closed. 设计:
#   - OPEN_MODE=true: 拒绝 POST (dev-user 是合成账户, 不能让所有 dev 都能改全局)
#     唯一豁免: ADMIN_USER_IDS env 含 "dev-user" 显式 (默认不含)
#   - OPEN_MODE=false: 要求 X-API-Key, user_id 必须在 ADMIN_USER_IDS (逗号分隔) 白名单
#   - GET (查询当前模式) 仍开放 — 不影响安全, 方便前端启动时拉取
_ADMIN_USER_IDS_RAW = os.getenv("ADMIN_USER_IDS", "").strip()
ADMIN_USER_IDS: frozenset[str] = frozenset(
    uid.strip() for uid in _ADMIN_USER_IDS_RAW.split(",") if uid.strip()
)


async def require_admin(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> User:
    """Admin 端点依赖. 严格 fail-closed, 跟 get_current_user 区别:

    1. OPEN_MODE=true → 拒绝 (返 403), 除非 ADMIN_USER_IDS 显式包含 "dev-user"
    2. OPEN_MODE=false → 校验 X-API-Key, user_id 必须在 ADMIN_USER_IDS 白名单

    ADMIN_USER_IDS 没配 → 任何 POST admin/* 都返 403 (默认安全).

    顺序: 先按 OPEN_MODE 决定认证策略, 再判 401/403:
      - OPEN_MODE=true + 无 dev-user 白名单 → 403 (不需要 key, 单纯拒绝)
      - OPEN_MODE=true + 有 dev-user 白名单 → 200 (合成 dev-user)
      - OPEN_MODE=false + 无 key → 401 (需要 key 才能继续)
      - OPEN_MODE=false + key 错 / 不在白名单 → 401 / 403
    """
    if OPEN_MODE:
        # 显式列表含 "dev-user" 才放行
        if "dev-user" in ADMIN_USER_IDS:
            logger.warning(
                "[SECURITY] OPEN_MODE=true + ADMIN_USER_IDS=dev-user: "
                "dev user 可改全局 LLM mode, 仅本地开发用"
            )
            return User(
                user_id="dev-user",
                display_name="Open Mode Dev (admin)",
                created_at=0.0,
                is_dev_user=True,
            )
        raise HTTPException(
            status_code=403,
            detail="OPEN_MODE=true 下 admin 端点默认拒绝. "
                   "如需在 dev 开放, 设 ADMIN_USER_IDS=dev-user (注意安全).",
        )
    # OPEN_MODE=false: 必须 key
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Admin 端点需要 X-API-Key header. "
                   "在 .env 设 ADMIN_USER_IDS=<逗号分隔 user_id 白名单> 授权.",
        )
    user = _lookup_user_by_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="API Key 无效或已撤销")
    if not ADMIN_USER_IDS:
        raise HTTPException(
            status_code=403,
            detail="Admin 端点未配置白名单. 在 .env 设 ADMIN_USER_IDS=<user_id> 授权.",
        )
    if user.user_id not in ADMIN_USER_IDS:
        # 模糊化日志: 不暴露白名单内容给攻击者
        logger.warning(
            f"[SECURITY] non-admin user {user.user_id[:8]}*** tried admin endpoint"
        )
        raise HTTPException(
            status_code=403,
            detail=f"User {user.user_id} 无 admin 权限. 联系管理员加入 ADMIN_USER_IDS 白名单.",
        )
    logger.info(f"[admin] user {user.user_id[:8]}*** granted admin access")
    return user


# ===== 业务逻辑 (auth 服务本身) =====
def issue_key_for_email(email: str, display_name: str = "") -> Optional[str]:
    """若 email 已注册, 返已有 key (重新登录); 否则注册新用户.

    注: 这是 'login' 端点, 实际是 '拿 key' 流程.  学术工具信任模型下
    email 即可证明身份 (高校邮箱 + 知网账号体系是常见模式).

    R10.5.25 (深度审计 §5): login 返 key 是故意行为, 让用户丢 key 后
    能重新拿. 副作用: 知道 email 的人能强制轮换 key, 让你掉线.
    缓解: per-IP + per-email 双重限流 (R10.5 Fix-P1-Audit-2.4), 加响应
    字段 key_rotated 告知前端是不是已有用户轮换.
    根治 (R11+ 计划): 改 OTP 邮件验证 + 多 session 并存.
    """
    result = issue_key_for_email_with_status(email, display_name)
    if result is None:
        return None
    return result[0]  # 仅 key, 向后兼容


def issue_key_for_email_with_status(
    email: str, display_name: str = ""
) -> Optional[tuple[str, bool]]:
    """R10.5.25: 同 issue_key_for_email, 额外返 (rotated: bool).

    rotated=True 表示 "已有用户 key 轮换" (说明 user 已存在).
    rotated=False 表示 "新用户首次注册".
    前端拿到 True 弹 '你的 API Key 已轮换, 旧 Key 失效' 警告.
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
        return (new_key, True)

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
    return (raw_key, False)  # 新用户, key_rotated=False
