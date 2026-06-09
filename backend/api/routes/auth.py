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

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend.auth.dependencies import (
    OPEN_MODE,
    User,
    get_current_user,
    issue_key_for_email,
    _register_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
# FastAPI 0.115+ compatibility: include_router accesses on_startup/on_shutdown
router.on_startup = []  # type: ignore[attr-defined]
router.on_shutdown = []  # type: ignore[attr-defined]


# ===== 请求/响应模型 =====
class RegisterRequest(BaseModel):
    # email 用 str 而非 pydantic EmailStr, 避免 email-validator 依赖.
    # 我们只用 email 派生 user_id, 格式校验在 issue_key_for_email 里做.
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


# ===== 端点 =====
@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest) -> AuthResponse:
    """注册新用户, 返一次性 API Key (丢失需 /auth/login 重新拿)."""
    if OPEN_MODE:
        # OPEN_MODE 模式下不创建新 user, 返 dev-user 占位
        # (高校部署必关 OPEN_MODE, 普通流程不影响)
        raise HTTPException(
            status_code=400,
            detail="OPEN_MODE=true 时不支持注册. 关闭 OPEN_MODE 后重启服务.",
        )
    user, api_key = _register_user(display_name=req.display_name or req.email)
    return AuthResponse(
        user_id=user.user_id,
        display_name=user.display_name,
        api_key=api_key,
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: RegisterRequest) -> AuthResponse:
    """用 email 拿 key. 已有用户返新 key (旧 key 失效), 新用户自动注册.

    学术工具信任模型: 高校邮箱是身份凭据. 不实现密码 (SMTP / OAuth
    留给 R11+).
    """
    if OPEN_MODE:
        raise HTTPException(
            status_code=400,
            detail="OPEN_MODE=true 时不需要 login. 关闭 OPEN_MODE 后重启服务.",
        )
    api_key = issue_key_for_email(req.email, display_name=req.display_name or req.email)
    if not api_key:
        raise HTTPException(status_code=400, detail="email 格式无效")
    # 取 user_id (issue 时已知是 email hash)
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
