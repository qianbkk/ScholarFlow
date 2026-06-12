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
from collections import OrderedDict, defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend.auth.dependencies import (
    OPEN_MODE,
    User,
    get_current_user,
    issue_key_for_email,
    # _register_user 已迁出, register/login 改用 issue_key_for_email. P1-2 移除死导入.
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
# 这里改用进程内 sliding window 限流, 单进程足够:
#  - 多 worker: 每个 worker 独立桶, 总容量 = N × limit. R11+ 上 Redis.
# 防 enumeration 攻击核心是"防止短时间大量尝试", 进程内 N×limit 仍可控.
# P0-3 fix (深度审计 §P0-3): _RATE_HISTORY 字典无界增长防护.
# 字典 key 本身从不删除 → 攻击者用无限伪造 IP 使字典无限膨胀.
# 改为 OrderedDict + LRU cap 1 万 + 定期清理 1 小时前的 stale key.
_RATE_HISTORY: "OrderedDict[str, deque[float]]" = OrderedDict()
_MAX_RATE_KEYS = 10_000
_RATE_CLEANUP_INTERVAL = 300  # 每 5 分钟清理一次 stale keys
_last_rate_cleanup: float = 0.0


def _maybe_cleanup_rate_history() -> None:
    """周期清理 1 小时前不活跃的 IP keys, 防止字典无界增长.
    触发条件: 距上次清理 ≥ _RATE_CLEANUP_INTERVAL."""
    global _last_rate_cleanup
    now = time.time()
    if now - _last_rate_cleanup < _RATE_CLEANUP_INTERVAL:
        return
    _last_rate_cleanup = now
    cutoff = now - 3600
    stale: list[str] = []
    for ip, history in _RATE_HISTORY.items():
        # 清空历史窗口外的旧时间戳
        while history and history[0] < cutoff:
            history.popleft()
        if not history:  # deque 空了, IP 1 小时无活动
            stale.append(ip)
    for ip in stale:
        _RATE_HISTORY.pop(ip, None)
    # LRU cap: 超 1 万就删最老的
    while len(_RATE_HISTORY) > _MAX_RATE_KEYS:
        _RATE_HISTORY.popitem(last=False)


def _parse_limit_string(limit_str: str) -> tuple[int | None, int | None]:
    """解析 "30/minute;200/hour" → (30, 200). None 表示无该窗口限制.

    支持的语法 (跟 slowapi 一致):
      "N/minute"     → (N, None)
      "N/hour"       → (None, N)
      "N/minute;M/hour" → (N, M)
      "1000/minute"  → (1000, None) — 极大值实际等于不限
    """
    per_min: int | None = None
    per_hour: int | None = None
    for part in limit_str.split(";"):
        part = part.strip()
        if "/minute" in part:
            per_min = int(part.split("/")[0])
        elif "/hour" in part:
            per_hour = int(part.split("/")[0])
    return per_min, per_hour


def _check_rate_limit(client_ip: str) -> None:
    """Sliding window 限流. 超限抛 429 (跟 slowapi 行为一致).

    R10.5.12: 限流按 ENVIRONMENT 分档 (config.RATE_LIMITS_CURRENT['auth_login']):
      dev  — 30/min 200/hour, test 1000/min (实际不限), prod 5/min 20/hour.
    P0-3 fix: 改用 OrderedDict + 定期清理, 防止字典无界增长.
    """
    import backend.config as _config
    limit_str = _config.RATE_LIMITS_CURRENT["auth_login"]
    max_per_minute, max_per_hour = _parse_limit_string(limit_str)
    now = time.time()
    _maybe_cleanup_rate_history()
    history = _RATE_HISTORY.get(client_ip)
    if history is None:
        history = deque()
        _RATE_HISTORY[client_ip] = history
    else:
        # 移到末尾 (LRU 更新)
        _RATE_HISTORY.move_to_end(client_ip)
    # 清掉窗口外的时间戳
    while history and now - history[0] > 3600:
        history.popleft()
    if max_per_hour and len(history) >= max_per_hour:
        raise HTTPException(
            status_code=429,
            detail=f"注册/登录请求过于频繁, 每小时最多 {max_per_hour} 次",
        )
    # 1 分钟内子窗口
    if max_per_minute:
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
