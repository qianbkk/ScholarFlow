"""backend.api.routes.auth — /auth/register + /auth/login (R10.5 Fix-P0-B)

多用户认证 + 高校部署 budget 隔离:
  POST /auth/register  {email, display_name} → {user_id, api_key}
  POST /auth/login     {email}              → {user_id, api_key}
  GET  /auth/me        X-API-Key header    → {user_id, display_name, ...}

OPEN_MODE=true 时这些端点仍可用, 但 /auth/me 返 dev-user.
OPEN_MODE=false 时 /auth/register + /auth/login 是新用户唯一入口.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend.auth.dependencies import (
    OPEN_MODE,
    User,
    get_current_user,
    issue_key_for_email,
    _register_user,
)
from backend.utils.network import get_real_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
# FastAPI 0.115+ compatibility
router.on_startup = []  # type: ignore[attr-defined]
router.on_shutdown = []  # type: ignore[attr-defined]


# ===== 请求/响应模型 =====
class RegisterRequest(BaseModel):
    # email 用 str 而非 pydantic EmailStr, 避免 email-validator 依赖.
    email: str = Field(..., min_length=3, max_length=254, description="学术邮箱 (作为 user_id 来源)")
    display_name: str = Field(default="", max_length=64, description="显示名")


class AuthResponse(BaseModel):
    user_id: str
    display_name: str
    api_key: str
    open_mode: bool = OPEN_MODE


class UserInfo(BaseModel):
    user_id: str
    display_name: str
    created_at: float
    open_mode: bool = OPEN_MODE


# ===== R10.5 Fix-P1-Audit-2.4: auth 端点限流 =====
# 不用 slowapi @limiter.limit 装饰器 — slowapi + FastAPI 2.12 / Pydantic 2.12
# 组合下, slowapi 的 wrapper 会把 body model (RegisterRequest) 误判成 Query 参数
# (ForwardRef('RegisterRequest') + Query() 嵌套), 触发 Pydantic 'TypeAdapter
# not fully defined' 错, 实际请求时 body 拿不到, 422 missing.
#
# 这里改用进程内 sliding window 限流 (5/minute;20/hour), 单进程足够:
#  - 单 worker 部署: 进程内 deque, 原子操作
#  - 多 worker: 每个 worker 独立桶, 总容量 = N × limit. R11+ 上 Redis.
# 防 enumeration 攻击核心是"防止短时间大量尝试", 进程内 N×limit 仍可控.
_RATE_HISTORY: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(client_ip: str, max_per_minute: int = 5, max_per_hour: int = 20) -> None:
    """Sliding window 限流. 超限抛 429 (跟 slowapi 行为一致)."""
    now = time.time()
    history = _RATE_HISTORY[client_ip]
    # 清掉窗口外的时间戳
    while history and now - history[0] > 3600:
        history.popleft()
    if len(history) >= max_per_hour:
        raise HTTPException(
            status_code=429,
            detail=f"注册/登录请求过于频繁, 每小时最多 {max_per_hour} 次",
        )
    # 1 分钟内子窗口
    one_min_ago = now - 60
    recent_minute = sum(1 for ts in history if ts > one_min_ago)
    if recent_minute >= max_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"注册/登录请求过于频繁, 每分钟最多 {max_per_minute} 次",
        )
    history.append(now)


# ===== 端点 =====
@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest) -> AuthResponse:
    """注册新用户, 返一次性 API Key (丢失需 /auth/login 重新拿).

    R10.5 Fix-X3: 跟 /auth/login 保持 user_id 派生一致 — 用 email sha256 派生,
    不再用 random UUID. 旧实现 register 用 UUID + login 用 email hash, 同一
    email register 跟 login 拿到不同 user_id, 跟 budget_user 隔离逻辑冲突.
    """
    # R10.5 Fix-P1-Audit-2.4: 进程内限流 (见 _check_rate_limit docstring)
    # 限流键用 email 字段, 防单 IP enumeration + 字典攻击
    client_key = f"email:{req.email.lower()}"
    _check_rate_limit(client_key)
    if OPEN_MODE:
        raise HTTPException(
            status_code=400,
            detail="OPEN_MODE=true 时不支持注册. 关闭 OPEN_MODE 后重启服务.",
        )
    # 跟 login 一致: email 已注册返新 key, 新 email 注册新用户
    api_key = issue_key_for_email(req.email, display_name=req.display_name or req.email)
    if not api_key:
        raise HTTPException(status_code=400, detail="email 格式无效")
    import hashlib
    user_id = "u_" + hashlib.sha256(req.email.lower().encode()).hexdigest()[:12]
    return AuthResponse(
        user_id=user_id,
        display_name=req.display_name or req.email,
        api_key=api_key,
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: RegisterRequest) -> AuthResponse:
    """用 email 拿 key. 已有用户返新 key (旧 key 失效), 新用户自动注册.

    学术工具信任模型: 高校邮箱是身份凭据. 不实现密码 (SMTP / OAuth
    留给 R11+).
    """
    # R10.5 Fix-P1-Audit-2.4: 进程内限流 (防字典攻击)
    client_key = f"email:{req.email.lower()}"
    _check_rate_limit(client_key)
    if OPEN_MODE:
        raise HTTPException(
            status_code=400,
            detail="OPEN_MODE=true 时不需要 login. 关闭 OPEN_MODE 后重启服务.",
        )
    api_key = issue_key_for_email(req.email, display_name=req.display_name or req.email)
    if not api_key:
        raise HTTPException(status_code=400, detail="email 格式无效")
    import hashlib
    user_id = "u_" + hashlib.sha256(req.email.lower().encode()).hexdigest()[:12]
    return AuthResponse(
        user_id=user_id,
        display_name=req.display_name or req.email,
        api_key=api_key,
    )


@router.get("/me", response_model=UserInfo)
async def me(user: User = Depends(get_current_user)) -> UserInfo:
    """返当前 user 信息, 验证 key 有效 (OPEN_MODE 返 dev-user)."""
    return UserInfo(
        user_id=user.user_id,
        display_name=user.display_name,
        created_at=user.created_at,
    )
