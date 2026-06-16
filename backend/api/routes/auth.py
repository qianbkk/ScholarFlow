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
import os
import time
from collections import OrderedDict, defaultdict, deque
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from typing import Optional

from backend.auth.dependencies import (
    OPEN_MODE,
    User,
    get_current_user,
    issue_key_for_email,
    issue_key_for_email_with_status,  # R10.5.25: 返 (key, rotated) 让前端警觉 Session DoS
    _hash_password,  # R10.5.28: 新注册 / 改密码 走 PBKDF2
    verify_password,  # R10.5.28: 登录校验密码
    _read_user_password,  # R10.5.28: 查 user 密码 hash
    _write_user_password,  # R10.5.28: 写 user 密码 hash
    # _register_user 已迁出, register/login 改用 issue_key_for_email. P1-2 移除死导入.
)
from backend.utils.network import get_real_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
# FastAPI 0.115+ compatibility
router.on_startup = []  # type: ignore[attr-defined]
router.on_shutdown = []  # type: ignore[attr-defined]


# R10.5.30 (D3): Set-Cookie 的 Secure flag 在 dev/test (HTTP) 下不能 True,
# 不然 TestClient / curl 不会存 cookie. 默认 False, 生产可设 SECURE_COOKIES=true.
def _is_cookie_secure() -> bool:
    return os.getenv("SECURE_COOKIES", "").lower() in ("1", "true", "yes")


# ===== 请求/响应模型 =====
class RegisterRequest(BaseModel):
    # email 用 str 而非 pydantic EmailStr, 避免 email-validator 依赖.
    email: str = Field(..., min_length=3, max_length=254, description="学术邮箱 (作为 user_id 来源)")
    display_name: str = Field(default="", max_length=64, description="显示名")
    # R10.5.28 (CG.txt 审计 P0 #1): 新注册必须设 password. 老用户 (password_hash=NULL)
    # 仍可 passwordless 登录, 但 lifespan 启动时强 WARN. 新流程要求 min 8 字符.
    password: str = Field(default="", min_length=0, max_length=128, description="密码 (>=8 字符; 老用户可空, 强烈建议填)")


class AuthResponse(BaseModel):
    user_id: str
    display_name: str
    api_key: str
    open_mode: bool = OPEN_MODE
    # R10.5.25 (深度审计 §5 修复): 告诉前端这次 login 是 "新注册" 还是
    # "已有用户 key rotation". 前端拿 true 时应该弹 "你的 API Key 已轮换,
    # 之前的 Key 已失效" 警告, 让用户警觉 Session DoS 攻击.
    key_rotated: bool = False


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
async def register(
    req: RegisterRequest,
    request: Request,  # R10.5.30 (D3 P0-1): Set-Cookie 需要 Request
    response: Response,
) -> AuthResponse:
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
    result = issue_key_for_email_with_status(
        req.email, display_name=req.display_name or req.email
    )
    if not result:
        raise HTTPException(status_code=400, detail="email 格式无效")
    api_key, rotated = result
    # R10.5.17: user_id 派生改用单源 helper (跟 audit log 一致).
    from backend.utils.user_id import hash_user_id
    user_id = hash_user_id(req.email)
    # R10.5.28 (CG.txt 审计 P0 #1): 新注册 / 重新注册 时若提供了 password
    # (>=8 字符) 走 PBKDF2 摘要落盘, 后续 /auth/login 强制校验.
    # 没传 password 时旧 user 保留 passwordless 行为, 但 lifespan 启动
    # 时 [SECURITY] WARN 提示管理员升级. 攻击者无法仅凭邮箱领 key 了.
    if req.password and len(req.password) >= 8:
        ph, salt = _hash_password(req.password)
        _write_user_password(user_id, ph, salt)
        logger.info(f"[auth/register] password set for {user_id[:8]}***")
    elif req.password and 0 < len(req.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="密码至少 8 字符, 请重新注册时设强密码.",
        )
    # R10.5.30 (D3 P0-1): 注册成功也 Set-Cookie (跟 login 一样)
    from backend.utils.session_store import create_session
    sess = create_session(user_id, ip_address=get_real_ip(request))
    response.set_cookie(
        key="sf_session_id",
        value=sess["session_id"],
        max_age=sess["ttl_sec"],
        httponly=True, secure=True, samesite="strict", path="/",
    )
    response.set_cookie(
        key="sf_csrf_token",
        value=sess["csrf_token"],
        max_age=sess["ttl_sec"],
        httponly=False, secure=True, samesite="strict", path="/",
    )
    return AuthResponse(
        user_id=user_id,
        display_name=req.display_name or req.email,
        api_key=api_key,
        key_rotated=rotated,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    req: RegisterRequest,
    request: Request,  # R10.5.30 (D3 P0-1): 用于 Set-Cookie + get_real_ip
    response: Response,  # R10.5.30 (D3 P0-1): 用于 Set-Cookie
) -> AuthResponse:
    """用 email 拿 key. 已有用户返新 key (旧 key 失效), 新用户自动注册.

    学术工具信任模型: 高校邮箱是身份凭据. 不实现密码 (SMTP / OAuth
    留给 R11+).

    R10.5.25 (深度审计 §5): 返 key_rotated 字段告诉前端"是否轮换了 key".
    前端拿 true 弹警告, 让用户警觉 Session DoS 攻击.

    R10.5.30 (D3 P0-1): 除返 api_key 外, 同时 Set-Cookie session_id +
    csrf_token (HttpOnly + Secure + SameSite=Strict). 前端 credentials:
    'include' 后, 写操作自动带 cookie + 必须在头显式带 X-CSRF-Token.
    """
    # R10.5 Fix-P1-Audit-2.4: 进程内限流 (防字典攻击)
    client_key = f"email:{req.email.lower()}"
    _check_rate_limit(client_key)
    if OPEN_MODE:
        raise HTTPException(
            status_code=400,
            detail="OPEN_MODE=true 时不需要 login. 关闭 OPEN_MODE 后重启服务.",
        )
    result = issue_key_for_email_with_status(
        req.email, display_name=req.display_name or req.email
    )
    if not result:
        raise HTTPException(status_code=400, detail="email 格式无效")
    api_key, rotated = result
    # R10.5.17: user_id 派生用 hash_user_id 单源 (跟 register / audit log 一致)
    from backend.utils.user_id import hash_user_id
    user_id = hash_user_id(req.email)
    # R10.5.30 (D3 P0-1): 创建 session, Set-Cookie 给前端. 双 cookie (session_id
    # HttpOnly + csrf_token JS-readable) 走双重提交 cookie 防 CSRF.
    from backend.utils.session_store import create_session
    sess = create_session(user_id, ip_address=get_real_ip(request))
    response.set_cookie(
        key="sf_session_id",
        value=sess["session_id"],
        max_age=sess["ttl_sec"],
        httponly=True,
        secure=_is_cookie_secure(),  # 生产强制 HTTPS, dev/test 走 .env 配置
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        key="sf_csrf_token",
        value=sess["csrf_token"],
        max_age=sess["ttl_sec"],
        httponly=False,  # CSRF token 必须 JS 可读才能放 X-CSRF-Token 头
        secure=_is_cookie_secure(),
        samesite="strict",
        path="/",
    )
    # R10.5.17: 同 register, 用 hash_user_id 单源
    from backend.utils.user_id import hash_user_id
    user_id = hash_user_id(req.email)
    # R10.5.28 (CG.txt 审计 P0 #1): login 必须校验 password (如果有).
    # 旧 user (password_hash=NULL) 仍可 passwordless 登录 (向后兼容),
    # 但 lifespan 启动时强 WARN. 新注册流程会强制 password, 攻击者仅
    # 凭邮箱拿不到 key.
    if not rotated:
        # 新用户走 register 路径, 不该走到 login. 直接拒.
        raise HTTPException(
            status_code=400,
            detail="邮箱未注册, 请先调用 /auth/register",
        )
    stored = _read_user_password(user_id)
    if stored is not None:
        # 用户有 password — 必须校验
        if not req.password:
            raise HTTPException(
                status_code=401,
                detail="此账户已设密码, 请提供 password 字段 (login 时).",
            )
        ph, salt = stored
        if not verify_password(req.password, ph, salt):
            logger.warning(
                f"[auth/login] WRONG PASSWORD for email={req.email.lower()} "
                f"user_id={user_id[:8]}***"
            )
            raise HTTPException(status_code=401, detail="密码错误")
        logger.info(f"[auth/login] password verified for {user_id[:8]}***")
    # R10.5.25: audit log 记录 key rotation, 防 Session DoS 难追溯
    if rotated:
        logger.info(
            f"[auth/login] KEY ROTATED for email={req.email.lower()} "
            f"user_id={user_id[:8]}***"
        )
    return AuthResponse(
        user_id=user_id,
        display_name=req.display_name or req.email,
        api_key=api_key,
        key_rotated=rotated,
    )


@router.get("/me", response_model=UserInfo)
async def me(user: User = Depends(get_current_user)) -> UserInfo:
    """返当前 user 信息, 验证 key 有效 (OPEN_MODE 返 dev-user)."""
    return UserInfo(
        user_id=user.user_id,
        display_name=user.display_name,
        created_at=user.created_at,
    )


# ===== R10.5.30 (D3 P0-1): HttpOnly cookie 登出 + CSRF token =====
class LogoutResponse(BaseModel):
    logged_out: bool
    user_id: Optional[str] = None


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
) -> LogoutResponse:
    """R10.5.30 (D3 P0-1): 登出 — 删 session, Set-Cookie 立即过期.

    鉴权依赖 (Cookie → User), 不需 X-CSRF-Token (登出是降权操作, 跨站请求
    反而帮用户清 cookie, 攻击者要的是登出, 不需防护; 但需 valid session).
    """
    from backend.utils.session_store import resolve_session, delete_session
    sess_id = request.cookies.get("sf_session_id")
    sess = resolve_session(sess_id) if sess_id else None
    user_id = sess["user_id"] if sess else None
    if sess_id:
        delete_session(sess_id)
    # 清 cookie — 立即过期
    response.delete_cookie("sf_session_id", path="/")
    response.delete_cookie("sf_csrf_token", path="/")
    return LogoutResponse(logged_out=True, user_id=user_id)


class CsrfTokenResponse(BaseModel):
    csrf_token: str
    expires_in: int


@router.get("/csrf-token", response_model=CsrfTokenResponse)
async def csrf_token_endpoint(
    request: Request,
    user: User = Depends(get_current_user),  # R10.5.30 (D3): 鉴权 (OPEN_MODE → dev-user)
) -> CsrfTokenResponse:
    """R10.5.30 (D3 P0-1): 给前端读 CSRF token (写到 X-CSRF-Token 头).

    双重提交 cookie 模式: CSRF token 存在 sf_csrf_token cookie (JS-readable,
    non-HttpOnly) + 后端 SQLite session 行里. 前端 fetch POST/PUT/DELETE
    时读 cookie 放到 X-CSRF-Token 头, 后端校验跟 session 行里一致.

    鉴权: OPEN_MODE=true → dev-user 可访问; false → 需 valid session.
    """
    from backend.utils.session_store import resolve_session
    if OPEN_MODE and user.is_dev_user:
        # OPEN_MODE=true: 没 session 也返一个伪 csrf_token, 方便 dev 测试
        # 真生产没 OPEN_MODE 时 user 必有 session.
        return CsrfTokenResponse(csrf_token="dev_mode_csrf_stub", expires_in=86400)
    sess_id = request.cookies.get("sf_session_id")
    sess = resolve_session(sess_id) if sess_id else None
    if not sess:
        raise HTTPException(
            status_code=401,
            detail="session 无效或过期, 请重新 /auth/login",
        )
    return CsrfTokenResponse(
        csrf_token=sess["csrf_token"],
        expires_in=86400,
    )


# ===== R10.5.25: stream token 替 ?api_key= query param =====
# 深度审计 §4: /search/stream?api_key=xxx 会泄露到 nginx log / browser history /
# proxy log. 短期方案: 发短期 stream token (5 分钟过期), 客户端用
# /search/stream?stream_token=xxx 替 ?api_key=. 5 分钟后 token 失效, log
# 留下也只暴露 5 分钟短命值, 不能拿来调其他端点.
#
# R11+ 计划: 改 EventSource Polyfill (fetch + ReadableStream + Authorization
# header), 完全消除 query param 凭证.

_STREAM_TOKEN_TTL_SEC = 300  # 5 min
_STREAM_TOKEN_DB = "stream_tokens"  # R10.5.28: SQLite 表名 (跨 worker 共享)


def _ensure_stream_token_table() -> None:
    """R10.5.28: stream_token 存 SQLite (跨 worker 共享). 旧实现是进程内 dict,
    4 worker gunicorn 下 A 发 token 会被 B 处理 / 取消失灵. 改 SQLite 后
    所有 worker 看到同一个 token 状态."""
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal("auth")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stream_tokens (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stream_tokens_expires ON stream_tokens(expires_at)")
        conn.commit()
    finally:
        conn.close()


def _new_stream_token(user_id: str) -> str:
    """生成短期 stream token, 存 SQLite 跨 worker 共享."""
    import secrets as _s
    _ensure_stream_token_table()
    token = "st_" + _s.token_urlsafe(24)
    expires = time.time() + _STREAM_TOKEN_TTL_SEC
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal("auth")
    try:
        conn.execute(
            "INSERT INTO stream_tokens (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, expires, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def _resolve_stream_token(token: str) -> str | None:
    """校验 stream token, 返 user_id 或 None (失效/不存在)."""
    if not token:
        return None
    _ensure_stream_token_table()
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal("auth")
    try:
        row = conn.execute(
            "SELECT user_id, expires_at FROM stream_tokens WHERE token=?",
            (token,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    user_id, expires = row
    if time.time() > expires:
        return None
    return user_id


def _gc_stream_tokens() -> None:
    """周期清理过期 stream tokens."""
    _ensure_stream_token_table()
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal("auth")
    try:
        now = time.time()
        conn.execute("DELETE FROM stream_tokens WHERE expires_at < ?", (now,))
        conn.commit()
    finally:
        conn.close()


# ===== R10.5.30 (D3 P0-1): CSRF 校验依赖 =====
# 双重提交 cookie 模式: POST/PUT/DELETE 必须带 X-CSRF-Token 头 (值跟
# sf_csrf_token cookie 一致), 且跟 server-side session 行里 csrf_token
# 一致. 这是 R10.5.30 真正修 CG.txt P1 #4 的关键 — 跨站请求攻击者读不到
# HttpOnly session_id, 也拿不到 JS-readable csrf_token (同源策略).
async def require_csrf(
    request: Request = None,  # type: ignore[assignment]
    x_csrf_token: Optional[str] = None,  # type: ignore[assignment]
) -> None:
    """FastAPI 依赖: 校验 X-CSRF-Token 头.

    1) 客户端必须带 sf_session_id cookie + X-CSRF-Token 头
    2) 头值必须跟 session.csrf_token 一致 (查 SQLite)
    3) 缺失 / 不匹配 → 403
    """
    if OPEN_MODE:
        # 开发模式: 跳过 CSRF, 简化测试
        return
    if not x_csrf_token:
        raise HTTPException(
            status_code=403,
            detail="缺少 X-CSRF-Token 头 (防 CSRF 攻击, 详情见 docs/CG.txt §1 P1 #4)",
        )
    sess_id = request.cookies.get("sf_session_id")
    if not sess_id:
        raise HTTPException(
            status_code=403,
            detail="缺少 session cookie, 请先 /auth/login",
        )
    from backend.utils.session_store import resolve_session
    sess = resolve_session(sess_id)
    if not sess:
        raise HTTPException(
            status_code=403,
            detail="session 无效或过期, 请重新 /auth/login",
        )
    if not hmac.compare_digest(sess["csrf_token"], x_csrf_token):
        raise HTTPException(
            status_code=403,
            detail="X-CSRF-Token 跟 session 不匹配",
        )


class StreamTokenResponse(BaseModel):
    token: str
    expires_in: int  # 秒


@router.post("/stream-token", response_model=StreamTokenResponse)
async def issue_stream_token(user: User = Depends(get_current_user)) -> StreamTokenResponse:
    """R10.5.25 (深度审计 §4 修复): 发短期 stream token 替 ?api_key=.

    客户端流程:
      1. fetch POST /auth/stream-token (X-API-Key header) → 拿 token
      2. EventSource('/search/stream?stream_token=' + token + '&q=...')
      3. 5 分钟内有效, 过期重新拿.

    防 log 泄露: api_key 长期有效, 一旦泄露到 nginx log 攻击者拿到后
    可以调任何端点; stream_token 5 分钟过期 + 仅 /search/stream 用,
    泄露后攻击窗口极小.
    """
    _gc_stream_tokens()
    return StreamTokenResponse(
        token=_new_stream_token(user.user_id),
        expires_in=_STREAM_TOKEN_TTL_SEC,
    )
