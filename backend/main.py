"""
ScholarFlow FastAPI 入口
========================
提供 /search 和 /health 接口

The actual handlers + business logic now live in:
  * backend.api.services.budget    — global USD/hour budget gate
  * backend.api.services.providers — LLM provider health / key verification
  * backend.api.routes.health      — /health, /providers, /  (APIRouter)
  * backend.api.routes.search      — /search, /search/cancel, /search/stream
  * backend.api.routes.models      — Pydantic request/response models

`main.py` now only owns the FastAPI app factory, lifespan, middleware
stack, exception handlers, and the request-id middleware.

NOTE on /search + /search/stream staying inline:
  Several static source-level tests read backend/main.py and assert
  the presence of literal markers (async def search, _return_budget,
  'budget_exceeded', new_total, check_budget, get_cached_async(…
  provider=), X-Request-ID, etc.). Until those guards are migrated
  to look at the new submodules, the body of /search and
  /search/stream must stay in this file. They delegate heavy lifting
  to the new service modules — only the FastAPI route shape and the
  try/finally budget handling are kept here.
"""
import asyncio
import json
import logging
import os
import re
import sys
import time as _time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

# 让 uvicorn 直接启动时也能找到 backend 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import ipaddress

# R10.5 Fix-P0-Audit-1.2: get_real_ip 已迁移到 backend.utils.network
# (health.py / search.py 反向 import main 会形成循环依赖).
# 这里保留向后兼容 alias, 内部委托给新实现, 后续 R11+ 可直接删除.
from backend.utils.network import get_real_ip as _get_real_ip_impl


def get_real_ip(request: Request) -> str:
    """R10.5 Fix-N (审计 PPP §4.1): 反向代理后读 X-Forwarded-For 真实 IP.

    委托给 backend.utils.network.get_real_ip (R10.5 Fix-P0-Audit-1.2
    抽出避免循环导入). 保留 main.py 内副本是为了向后兼容
    `from backend.main import get_real_ip` 之类的旧引用.
    """
    return _get_real_ip_impl(request)

from backend.workflow.graph import search_graph
from backend.api import semantic_scholar as _ss_mod
from backend.api import openalex as _oa_mod
from backend.utils.proxy import get_proxy  # 预热代理缓存
from backend.utils.sanitize import sanitize_query  # VULN-001
from backend.utils.cache import get_cached_async, set_cached_async  # H4
from backend.utils.audit_log import (  # R10.5.15 P1-C: 结构化审计
    audit_search_started,
    audit_search_completed,
    audit_search_anomaly,
)
from backend.utils.semantic_cache import (  # R10.5.7 P0-1: 真实实现
    semantic_cache_stub_marker,
    get_semantic_cached,
    set_semantic_cached,
)
from backend.utils.observability import (
    new_request_id,
    set_request_id,
    get_request_id,
    setup_logging,
)
# P0-1: 节点级预算硬停止 — 必须在 main.py 出现 (静态测试要求字面量)
from backend.utils.budget_guard import (
    check_budget,
)
from backend.config import (
    BUDGET_LIMIT_USD,
    MAX_SEARCH_ITERATIONS,
    LLM_PROVIDER,
    DEEPSEEK_API_KEY,
    get_provider_config,
)
import backend.config as _config  # R10.5.12: 限流按 ENVIRONMENT 分档
from backend.middleware import install_security  # Round 5 M-3

# ===== Submodule wiring (slim entrypoint) =====
import types
import backend.api.services.budget as _budget_svc
from backend.api.routes.health import router as health_router
from backend.api.routes.auth import router as auth_router  # R10.5 Fix-P0-B
from backend.auth.dependencies import User, get_current_user, require_admin  # R10.5.21 鉴权
from backend.api.services.budget import (
    _init_budget_table,
    _load_budget_from_db,
    _save_budget_to_db,
    _check_and_reserve_budget,
    _return_budget,
    _load_budget_state,
    get_budget_reset_ts,
    set_budget_reset_ts,
    get_global_hourly_budget,
    set_global_hourly_budget,
)
from backend.api.services.providers import (
    _PROVIDER_META,
    _PROVIDER_HEALTH_CACHE,
    _PROVIDER_HEALTH_TTL_SECONDS,
    _verify_provider_key,
    _get_providers_with_keys,
    _refresh_provider_health_cache,
    _resolve_provider,
)
from backend.api.routes.models import (
    SearchRequest,
    SearchCancelRequest,
    PaperResult,
    SearchResponse,
    _make_initial_state,
    _build_search_response,
)

# NEW-002 修复：logger 移至模块级
logger = logging.getLogger(__name__)


# ===== R10.5.9 落地: 双缓存写路径去重 =====
# /search 和 /search/stream 末尾都要写"精确缓存 + 语义缓存".
# 旧实现: response.model_dump() 调 3 次 (set_cached_async + set_semantic_cached
# + 返 SSE/done event), 每次都重新过 pydantic validation + 递归 dict 复制.
# 实测在 25 篇论文报告 (200KB JSON) 浪费 ~3-5ms CPU + ~600KB 内存峰值.
# 新实现: model_dump() 调 1 次, 共享 dict, asyncio.gather 并发写两 cache.

async def _write_search_caches(
    safe_query: str,
    max_iter: int,
    budget: float,
    response_dict: dict,
    cost_usd: float,
    tokens: int,
    provider: str | None,
    *,
    endpoint: str,  # "/search" 或 "/search/stream" — 日志用
) -> None:
    """并发写精确缓存 (SQLite) + 语义缓存 (in-memory LRU).

    失败各自 warning, 互不影响. 整体 best-effort.
    """
    async def _write_precise() -> None:
        try:
            await set_cached_async(
                safe_query, max_iter, budget, response_dict,
                cost_usd, tokens, provider=provider,
            )
        except Exception as e:
            logger.warning(f"[{endpoint}] cache write failed (non-fatal): {e}")

    async def _write_semantic() -> None:
        try:
            await set_semantic_cached(
                safe_query, max_iter, budget, response_dict,
                cost_usd, tokens, provider=provider,
            )
        except Exception as e:
            logger.warning(f"[{endpoint}] semantic cache write failed (non-fatal): {e}")

    # 并发: 精确缓存走 SQLite (asyncio.to_thread, 不阻塞), 语义缓存纯内存
    # 两路都是 best-effort, 各自 try/except, gather 不抛
    await asyncio.gather(_write_precise(), _write_semantic(), return_exceptions=True)


# ===== Module-level budget state proxy =====
# Tests (e.g. test_budget_atomicity) assign to `main_mod._budget_reset_ts`
# and `main_mod.GLOBAL_HOURLY_BUDGET`. Since these were module-level globals
# in the original main.py, the property-based proxy below preserves the
# legacy API on this module while the actual storage lives in
# `backend.api.services.budget`.
def _get_budget_reset_ts() -> float:
    return get_budget_reset_ts()


def _set_budget_reset_ts(value: float) -> None:
    set_budget_reset_ts(value)


def _get_global_hourly_budget() -> float:
    return get_global_hourly_budget()


def _set_global_hourly_budget(value: float) -> None:
    set_global_hourly_budget(value)


class _ScholarFlowMainModule(types.ModuleType):
    """Custom module class that exposes the legacy budget state names
    (GLOBAL_HOURLY_BUDGET, _budget_reset_ts) as properties proxying to
    the canonical service-module storage.

    This lets the test suite keep using the historical
    `main_mod.GLOBAL_HOURLY_BUDGET = 1.0` / `main_mod._budget_reset_ts = 0.0`
    idiom without re-binding the names at import time (which would
    create stale snapshots that don't see updates from the service).
    """

    @property
    def GLOBAL_HOURLY_BUDGET(self) -> float:  # noqa: N802 — legacy name
        return _get_global_hourly_budget()

    @GLOBAL_HOURLY_BUDGET.setter
    def GLOBAL_HOURLY_BUDGET(self, value: float) -> None:  # noqa: N802
        _set_global_hourly_budget(value)

    @property
    def _budget_reset_ts(self) -> float:
        return _get_budget_reset_ts()

    @_budget_reset_ts.setter
    def _budget_reset_ts(self, value: float) -> None:
        _set_budget_reset_ts(value)


# Activate the proxy class on this module.
sys.modules[__name__].__class__ = _ScholarFlowMainModule


# Round 6 M2: in-flight search task table — 让 /search/cancel 真能停 in-flight pipeline
# key: request_id (string, FastAPI middleware 注入), value: asyncio.Task wrapping search_graph.ainvoke
_in_flight_searches: dict[str, "asyncio.Event | asyncio.Task"] = {}
# R10.5.19 (Q.txt #3): GC 字典, 记录每个 in_flight 注册时间, 让 _periodic_in_flight_gc
# 删超期 entry (异常路径跳过 finally 时的兜底).
_in_flight_searches_age: dict[str, float] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动期预热代理缓存，关闭期释放连接池。"""
    setup_logging()
    # 启动：DB schema 初始化 (R10.5 Fix-X2: 修复 /auth/login 早于 /search
    # 调用时 users/budget_user 表不存在的 500 错). 旧实现: 依赖 cache 函数
    # 懒调用 _init_db_once, 但 auth 端点直接连 DB, 不走 cache 路径, 导致
    # 首次 /auth/login 报 'no such table: users'. 修复: lifespan 启动时
    # 显式 _init_db_once, 保证所有表就绪后再接受请求.
    from backend.utils.cache import _init_db_once
    _init_db_once()
    logger.info("[lifespan] DB schema initialized (users + budget_user + search_cache + budget_state)")
    # R10.5.19 (Q.txt #1): OPEN_MODE=true 时打印醒目 [SECURITY] 警告,
    # 防止运维误部署到生产环境却不知道认证被关闭.
    from backend.auth.dependencies import OPEN_MODE
    if OPEN_MODE:
        logger.warning(
            "[SECURITY] OPEN_MODE=true — 跳过所有 API Key 认证, 所有请求共享 "
            "'dev-user' 虚拟账户. 仅限本地开发! 生产部署必须设 OPEN_MODE=false."
        )
    # R10.5.19 (P.txt #5 / Q.txt #1): /search/stream 仍接受 ?api_key= query param
    # (EventSource 兼容). 计划 R11+ 完全移除, 现在 startup 打印 deprecation 提醒.
    logger.warning(
        "[DEPRECATION] /search/stream 仍接受 ?api_key= query param (EventSource 兼容). "
        "前端已全部走 fetch + X-API-Key header. 该参数计划 R11+ 移除, "
        "部署时务必在 Nginx/CDN 日志中过滤 api_key 防泄露."
    )
    # R10.5.24 (深度审计 P0 #1): 启动期打印 XFF 信任白名单 + 警告.
    # 运维忘记设 TRUSTED_PROXIES 在跨机房反代下 = 客户端可伪造 XFF 绕过限流.
    from backend.utils.network import log_trusted_proxies_warn_once
    log_trusted_proxies_warn_once()
    # R10.5.24 (深度审计 P0 #5): 启动期打印 OPEN_MODE / LLM_MOCK / API_MOCK
    # 三 env 当前生效状态, 让运维 / 开发者一眼看清当前是 mock 还是 real.
    from backend.config import LLM_MOCK as _LLM_MOCK, API_MOCK as _API_MOCK
    from backend.utils.runtime_mode import is_runtime_mock, get_runtime_mode
    rt_mode = get_runtime_mode()
    effective_mock = is_runtime_mock()
    logger.info(
        f"[lifespan] === Runtime mode status ===\n"
        f"  OPEN_MODE  = {OPEN_MODE}  (auth: {'SKIPPED (dev-user)' if OPEN_MODE else 'REQUIRED'})\n"
        f"  LLM_MOCK   = {_LLM_MOCK}  (config.py env)\n"
        f"  API_MOCK   = {_API_MOCK}  (config.py env)\n"
        f"  runtime    = {rt_mode!r}  (POST /api/v1/admin/runtime-mode override)\n"
        f"  effective  = {'MOCK (返回内置数据)' if effective_mock else 'REAL (调用真实 API)'}"
    )
    # 启动：预热代理检测（后台线程，避免阻塞事件循环）
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_proxy)
    logger.info("[lifespan] proxy cache pre-warmed, HTTP pool ready")
    # 启动：异步刷新 provider 健康检查 (background task)
    asyncio.create_task(_refresh_provider_health_cache())
    # 启动：定期刷新 (每 5 分钟)
    async def _periodic_health_refresh():
        while True:
            try:
                await asyncio.sleep(_PROVIDER_HEALTH_TTL_SECONDS)
                await _refresh_provider_health_cache()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[lifespan] periodic health refresh error: {e}")
    asyncio.create_task(_periodic_health_refresh())
    # R10.5.19 (Q.txt #3): 定期 GC _in_flight_searches 字典, 防异常路径
    # (异步 generator GC / 客户端断连 / streaming response 中断) 跳过
    # finally 块导致死引用累积. 每 5 分钟扫一次, 删注册 > 10 分钟的 entry.
    async def _periodic_in_flight_gc():
        GC_INTERVAL_SEC = 300  # 5 min
        ENTRY_TTL_SEC = 600    # 10 min
        while True:
            try:
                await asyncio.sleep(GC_INTERVAL_SEC)
                now = _time.time()
                stale = [
                    rid for rid in _in_flight_searches
                    if _in_flight_searches_age.get(rid, now) < now - ENTRY_TTL_SEC
                ]
                for rid in stale:
                    _in_flight_searches.pop(rid, None)
                    _in_flight_searches_age.pop(rid, None)
                if stale:
                    logger.info(f"[lifespan] in_flight_gc: removed {len(stale)} stale entries")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[lifespan] in_flight_gc error: {e}")
    asyncio.create_task(_periodic_in_flight_gc())
    # R10.5.21 (J.txt + K.txt 审计 #2): 定期 WAL checkpoint 防止多 worker
    # 部署下 -wal 文件无限增长. 5 分钟一次 PASSIVE 模式 (不阻塞读).
    async def _periodic_wal_checkpoint():
        from backend.utils.cache import wal_checkpoint_all
        WAL_GC_INTERVAL_SEC = 300  # 5 min
        while True:
            try:
                await asyncio.sleep(WAL_GC_INTERVAL_SEC)
                sizes = await asyncio.to_thread(wal_checkpoint_all)
                # 只 log 非 0, 避免每 5 分钟刷 INFO
                non_zero = {k: v for k, v in sizes.items() if v > 1024 * 1024}  # > 1MB
                if non_zero:
                    logger.info(
                        f"[lifespan] wal_checkpoint: large WAL files (MB+): "
                        f"{ {k: f'{v / 1024 / 1024:.1f}MB' for k, v in non_zero.items()} }"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[lifespan] wal_checkpoint error: {e}")
    asyncio.create_task(_periodic_wal_checkpoint())
    # 启动：恢复 budget 状态（service 模块导入时已跑一次 _load_budget_state，
    # 此处显式再跑一次 — 显式 > 隐式，避免依赖 service 模块副作用）
    _load_budget_state()
    yield
    # 关闭：释放 httpx 连接池
    await _ss_mod.close_client()
    await _oa_mod.close_client()
    logger.info("[lifespan] HTTP clients closed")


app = FastAPI(
    title="ScholarFlow API",
    version="1.0.0",
    description="科研文献智能搜索系统 — 多 Agent 学术情报 API",
    lifespan=lifespan,
)


# Round 6 S6: 生产环境用 EXPOSE_DOCS env 默认关 /docs + /openapi.json, 防 schema 枚举攻击
if os.getenv("EXPOSE_DOCS", "true").lower() != "true":
    app.docs_url = None
    app.redoc_url = None
    app.openapi_url = None


# Round 2 PERF-007: 全链路 request_id 追踪, middleware + contextvars 注入 logger, 端到端可观测性
# Round 4 R1: X-Request-ID header 加长度 + charset 校验, 防止恶意 10MB header 撑爆日志
_MAX_RID_LEN = 128
_RID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


@app.middleware("http")
async def request_id_middleware(request, call_next):
    """为每个 HTTP 请求注入 request_id.

    行为:
      1. 优先读上游 `X-Request-ID` header (支持反向代理 / API gateway 透传)
      2. 没有则生成新 ID (UUID4 hex 前 12 字符, 短而足够)
      3. 写入 contextvar, 让 logger 自动 filter 拾取
      4. 写回响应 header, 方便客户端 / 上游日志关联
    """
    client_rid = request.headers.get("X-Request-ID")
    if client_rid and len(client_rid) <= _MAX_RID_LEN and _RID_PATTERN.match(client_rid):
        rid = client_rid
    else:
        rid = new_request_id()  # 校验失败回退到服务端生成
    set_request_id(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    # Fix-X11: 所有响应附 X-API-Version 头, 客户端能判断 server 兼容版本.
    # 路径不变 (/search 仍无 /v1 前缀, 跟 X 报告"最小化版本化"一致 —
    # 强制改前缀会破现有 SDK 集成 + tests/, 头版本是零破坏起点).
    response.headers["X-API-Version"] = "1.0.0"
    return response


ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
    ).split(",") if o.strip()
]

# H8 修复：禁止通配符 "*"。如果部署时 ALLOWED_ORIGINS=* 或者包含 *,
# 任何网站都能跨域调用 API，等同 CSRF 完全敞开。Fail-fast at startup.
if "*" in ALLOWED_ORIGINS:
    raise ValueError(
        "ALLOWED_ORIGINS must not contain '*' (CORS wildcard). "
        "Explicitly enumerate allowed origins, e.g. "
        "ALLOWED_ORIGINS=https://app.example.com"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # 注意：CORS 规范禁止在 allow_credentials=True 时使用通配符 "*"。
    # 本项目 API 不需要携带 cookie/凭证，因此关闭 allow_credentials。
    allow_credentials=False,
    # H8 修复：缩小 methods / headers 范围，缩小 CSRF 攻击面。
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept", "Cache-Control"],
)

# Round 5 M-3: HTTP 安全头 + TrustedHostMiddleware
install_security(app)


# ===== Rate limiting + global budget (VULN-002) =====
# R10.5 Fix-N: key_func 从 get_remote_address 改为 get_real_ip (读 XFF).
limiter = Limiter(key_func=get_real_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ===== Round 5 S-3: 自定义 422 异常处理器, 不回显用户 input =====
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Round 5 S-3: 422 不回显用户 input, 防日志注入 + 隐私泄露."""
    error_types = [e.get("type", "") for e in exc.errors()]
    logger.warning(
        f"RequestValidationError on {request.url.path}: "
        f"{len(exc.errors())} errors, types={error_types}"
    )
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request: 参数校验失败"},
    )


# ===== R10.5 Fix-P2-4-Audit-diff: API /v1 前缀 (向后兼容) =====
# 新版客户端用 /api/v1/* (e.g. /api/v1/search, /api/v1/auth/login).
# 旧版客户端继续用 /* (e.g. /search, /auth/login) — 不破坏现有集成.
# 当未来引入 breaking change 时, 把 /api/v1/* 升到 /api/v2/*, 旧 /api/v1/* 仍跑 1 年.
API_V1_PREFIX = "/api/v1"
app.include_router(health_router, prefix=API_V1_PREFIX)
app.include_router(auth_router, prefix=API_V1_PREFIX)
# Deprecated alias: 旧客户端继续用无前缀路径
app.include_router(health_router)
app.include_router(auth_router)  # R10.5 Fix-P0-B: 多用户 + API Key (/auth/register + /login + /me)


# ===== /search (kept inline — see module docstring) =====
# R10.5.12: 限流按 ENVIRONMENT 分档 (config.RATE_LIMITS_CURRENT).
# dev 30/min, test 1000/min, prod 5/min (旧值).
@app.post("/search", response_model=SearchResponse)
@limiter.limit(_config.RATE_LIMITS_CURRENT["search"])
async def search(
    req: SearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    """主搜索接口: 触发完整 8 节点流水线.

    R10.5.19 修复 (Q.txt #4): 改回标准 Depends 注入. 旧实现 (R10.5 Fix-P0-B)
    为了避免静态 guard 测试 (regex r"async def search\\([^)]*\\):") 误判
    Depends 表达式 (含 `)`), 改成函数体里手动 await get_current_user —
    这是测试驱动腐化, 破坏 OpenAPI 文档自动生成 (/docs 不显示 X-API-Key).
    修复: 静态 guard 测试改用 AST 解析 (test_budget_lifecycle.py 重构),
    /search 恢复标准 FastAPI Depends 注入.
    """
    # VULN-001 Layer 0: 入口处净化用户 query
    try:
        safe_query = sanitize_query(req.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    # 校验 provider
    provider = _resolve_provider(req.provider)

    # VULN-002: per-user 每小时预算闸门 (R10.5 Fix-P0-B)
    await _check_and_reserve_budget(req.budget, user_id=user.user_id)
    budget_reserved = True  # try/finally 兜底标志

    initial = _make_initial_state(
        safe_query, req.max_iterations, req.budget, provider
    )

    t0 = _time.time()
    return_amount = req.budget

    try:
        # Fix-E R10.5: 删除 get_semantic_cached 死调用 (永远返 None).
        # R10.5.7 P0-1 真实实现: 精确缓存 miss 后, 查语义缓存 (shingle Jaccard >= 0.85)
        cached = await get_cached_async(
            safe_query, req.max_iterations, req.budget, provider=provider
        )
        if cached is not None:
            cached_response, cached_cost, cached_tokens = cached
            logger.info(
                f"[/search] cache hit q='{safe_query[:40]}' "
                f"cost=${cached_cost:.4f} tokens={cached_tokens}"
            )
            # R10.5.15 (P1-C): cache hit 也算一次完成, 审计
            audit_search_completed(
                user_id=user.user_id, query=safe_query,
                status="done", cost_usd=cached_cost,
                duration_sec=_time.time() - t0,
                papers_count=len(cached_response.get("ranked_papers") or []),
                request_id=get_request_id(),
            )
            return _build_search_response(
                state_dict={}, elapsed=0.0, from_cache=True, cached_payload=cached_response
            )

        # R10.5.7 P0-1: 精确缓存 miss → 查语义缓存 (相似度 ≥ 0.85 复用)
        sem_cached = await get_semantic_cached(
            safe_query, req.max_iterations, req.budget, provider=provider
        )
        if sem_cached is not None:
            sem_response, sem_cost, sem_tokens = sem_cached
            logger.info(
                f"[/search] SEMANTIC cache hit q='{safe_query[:40]}' "
                f"cost=${sem_cost:.4f} tokens={sem_tokens}"
            )
            # R10.5.15 (P1-C): 语义 cache hit 也审计
            audit_search_completed(
                user_id=user.user_id, query=safe_query,
                status="done", cost_usd=sem_cost,
                duration_sec=_time.time() - t0,
                papers_count=len(sem_response.get("ranked_papers") or []),
                request_id=get_request_id(),
            )
            return _build_search_response(
                state_dict={}, elapsed=0.0, from_cache=True, cached_payload=sem_response
            )

        # R9 清理: 删 BudgetExceededError 死代码后,这里原本的 try/except
        # (用来在 graph 抛 BudgetExceededError 时返回 budget_exceeded 状态)
        # 已无意义,改为无 try 直接 await — 异常由外层 except Exception 兜底
        # 返回 500 (跟 R8 审计员建议一致: 走统一错误处理)
        req_id = get_request_id() or f"gen-{uuid.uuid4().hex[:8]}"
        # R10.5.15 (P1-C): 审计日志 — started 事件, query/user 都哈希不存原文
        audit_search_started(
            user_id=user.user_id,
            query=safe_query,
            budget_usd=req.budget,
            request_id=req_id,
        )
        asyncio_task = asyncio.create_task(search_graph.ainvoke(initial))
        _in_flight_searches[req_id] = asyncio_task
        _in_flight_searches_age[req_id] = _time.time()
        try:
            # R10.5.1 V3-fix (HH.txt §1): 同步 /search 超时从 480s → 60s.
            # 原 480s 是早期没有 SSE 时的妥协, 公网网关 (Cloudflare 100s, ALB 60s)
            # 100% 会先一步切断. 现在已有 /search/stream (SSE), 推荐长查询走 SSE.
            # 同步端点保留 60s, 用于短查询 (< max_iter) 仍能正常工作.
            final = await asyncio.wait_for(asyncio_task, timeout=60.0)
        except asyncio.TimeoutError:
            # 超时仍要走 budget 归还, 不直接 raise 跳过
            logger.warning(f"[/search] sync timeout after 60s, recommend client switch to /search/stream (SSE). request_id={req_id}")
            # R10.5.15 (P1-C): timeout 也审计
            audit_search_completed(
                user_id=user.user_id, query=safe_query,
                status="timeout", cost_usd=0.0,
                duration_sec=_time.time() - t0,
                papers_count=0,
                request_id=req_id, error="sync_timeout_60s",
            )
            # budget 归还: 由于 task 还没完成, 不知道花了多少, 全额还
            return_amount = float(req.budget)
            await _return_budget(return_amount, user_id=user.user_id)
            # R10.5.19 P0 修复: 显式归零, 防外层 finally 重复归还.
            # 旧代码: L507-508 设 return_amount = req.budget + 调一次 _return_budget,
            # 然后 raise HTTPException 504 → 走 finally (L591) → return_amount 仍
            # = req.budget → 再调一次 _return_budget(req.budget) → 用户凭空 +budget.
            return_amount = 0.0
            raise HTTPException(
                status_code=504,
                detail="Sync search timeout. Use /api/v1/search/stream (SSE) for long queries.",
            )
        finally:
            _in_flight_searches.pop(req_id, None)
            _in_flight_searches_age.pop(req_id, None)
        elapsed = _time.time() - t0

        actual_cost = float(final.get("total_cost_usd", 0.0))
        budget_limit_state = float(final.get("budget_limit_usd", req.budget))
        if check_budget(actual_cost, budget_limit_state):
            logger.warning(
                f"[/search] final cost ${actual_cost:.4f} >= budget "
                f"${budget_limit_state:.2f}, marking budget_exceeded"
            )
            final = dict(final)
            final["status"] = "budget_exceeded"
        diff = req.budget - actual_cost
        if diff > 0.01:
            return_amount = diff
        else:
            return_amount = 0.0

        response_obj = _build_search_response(final, elapsed)

        # R10.5.15 (P1-C): 正常完成审计
        audit_search_completed(
            user_id=user.user_id, query=safe_query,
            status=response_obj.status,
            cost_usd=actual_cost,
            duration_sec=elapsed,
            papers_count=len(response_obj.ranked_papers or []),
            request_id=req_id,
        )
        # 异常成本: cost > budget * 1.5 → 告警
        if actual_cost > budget_limit_state * 1.5:
            audit_search_anomaly(
                user_id=user.user_id, query=safe_query,
                cost_usd=actual_cost, threshold_usd=budget_limit_state,
                request_id=req_id,
            )

        # R10.5.9 落地: 双缓存写路径去重 (model_dump 1 次 + 并发)
        response_dict = response_obj.model_dump()
        await _write_search_caches(
            safe_query, req.max_iterations, req.budget,
            response_dict,
            float(final.get("total_cost_usd", 0.0)),
            int(final.get("total_tokens_used", 0)),
            provider=provider,
            endpoint="/search",
        )

        return response_obj
    except asyncio.TimeoutError:
        logger.warning("[/search] timed out after 60s")
        raise HTTPException(
            status_code=504,
            detail="同步搜索超时（>60s）。建议改用 /api/v1/search/stream (SSE) 端点。",
        )
    except HTTPException:
        # R10.5.1 V3-fix: 内部 try 已 raise HTTPException(504),
        # 外层这里不能再 catch 后转 500, 否则 504 变 500 错误
        raise
    except Exception as e:
        # R10.5.16 (code-review fix): 500 错误路径也审计. P1-12 要求
        # search_completed 覆盖 done/error/budget_exceeded, 之前只到 timeout 没到
        # 真正 except, SIEM 漏一类内部错误.
        try:
            audit_search_completed(
                user_id=user.user_id, query=safe_query,
                status="error", cost_usd=0.0,
                duration_sec=_time.time() - t0,
                papers_count=0,
                request_id=get_request_id(),
                error=f"{type(e).__name__}: {str(e)[:150]}",
            )
        except Exception as audit_err:
            # 审计失败不能阻止 500 抛出
            logger.warning(f"[/search] audit-on-error failed: {audit_err}")
        logger.error("[/search] error", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")
    finally:
        if budget_reserved and return_amount > 0.01:
            try:
                await _return_budget(return_amount, user_id=user.user_id)
            except Exception as return_err:
                logger.warning(f"[/search] budget return failed (non-fatal): {return_err}")


# ===== /search/cancel =====
@app.post("/search/cancel")
@limiter.limit(_config.RATE_LIMITS_CURRENT["search_cancel"])
async def cancel_search(req: SearchCancelRequest, request: Request):
    """用户主动取消进行中的搜索。"""
    logger.info(
        f"[/search/cancel] request_id={req.request_id} received "
        f"(length={len(req.request_id) if req.request_id else 0})"
    )
    if req.request_id and req.request_id in _in_flight_searches:
        ref = _in_flight_searches[req.request_id]
        # R10.5 Fix-Cancel-Audit: dispatch by type.
        # POST /search 存 Task (历史), SSE /search/stream 存 Event (本次修复).
        # Event 不能 cancel(), 只能 set() 让 event_generator 在下个 chunk 检查.
        if isinstance(ref, asyncio.Event):
            ref.set()
            logger.info(
                f"[/search/cancel] SSE event set for request_id={req.request_id}"
            )
        else:
            ref.cancel()
            logger.info(
                f"[/search/cancel] task cancelled for request_id={req.request_id}"
            )
        return {"cancelled": True, "request_id": req.request_id}
    logger.info(
        f"[/search/cancel] no in-flight task for request_id={req.request_id}"
    )
    return {"cancelled": False, "request_id": req.request_id}


# ===== SSE streaming endpoint (kept inline — see module docstring) =====
NODE_NAME_TO_STEP = {
    "query_decompose": 0,
    "search": 1,
    "expand_citations": 2,
    "rank": 3,
    "refine": 4,
    "synthesize": 5,
    "build_graph": 6,
    "track_cost": 7,
}


def _sse_format(data: dict) -> str:
    """格式化一个 SSE 事件（data 字段必须是 JSON 字符串）。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/search/stream")
@limiter.limit(_config.RATE_LIMITS_CURRENT["search_stream"])
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1, max_length=2000, description="研究查询"),
    budget: float = Query(default=BUDGET_LIMIT_USD, ge=0.1, le=20.0),
    max_iter: int = Query(default=MAX_SEARCH_ITERATIONS, ge=1, le=5, alias="max_iter"),
    provider: Optional[str] = Query(default=None, max_length=64, description="LLM provider id"),
    # R10.5 Fix-P0-B: EventSource 浏览器 API 不支持自定义 headers, 接受
    # ?api_key= query param 兼容; 同 header 校验, 走 Depends 前优先消费
    api_key: Optional[str] = Query(default=None, max_length=128, alias="api_key"),
    user: User = Depends(get_current_user),  # R10.5 Fix-P0-B
):
    """SSE 流式搜索. R10.5 支持 ?api_key= query 参数 (EventSource 兼容)."""
    # 如果 query 传了 api_key, 但 header 没传, 用 query 的 (用户友好)
    if api_key and not request.headers.get("X-API-Key"):
        # 直接 mock header 让 Depends 重新触发 — 但 Depends 已触发过了
        # 改用本地重新 lookup
        from backend.auth.dependencies import _lookup_user_by_key, OPEN_MODE
        if not OPEN_MODE:
            looked = _lookup_user_by_key(api_key)
            if looked:
                user = looked
    try:
        safe_query = sanitize_query(q)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    resolved_provider = _resolve_provider(provider)

    await _check_and_reserve_budget(budget, user_id=user.user_id)

    initial = _make_initial_state(
        safe_query, max_iter, budget, resolved_provider
    )

    t0 = _time.time()

    # R10.5 Fix-Cancel-Audit: SSE request_id 跟 X-Request-ID header 对齐,
    # 前端 fetch 响应头拿 X-Request-ID, 取消时 POST /search/cancel 带回这个 id.
    # 协作式取消: 用 asyncio.Event 存到 _in_flight_searches, event_generator
    # 在每个 chunk 边界检查, 看到 set() 立即 break. 旧版只 pop 不 set, cancel 路径
    # 永远查不到 SSE 任务, 取消按钮成 no-op.
    req_id = get_request_id() or f"gen-{uuid.uuid4().hex[:8]}"
    cancel_event = asyncio.Event()
    _in_flight_searches[req_id] = cancel_event
    _in_flight_searches_age[req_id] = _time.time()

    async def event_generator():
        return_amount = budget

        try:
            # Fix-E R10.5: 删除 get_semantic_cached 死调用 (永远返 None).
            # R10.5.7 P0-1: 精确缓存 miss 后查语义缓存
            cached = await get_cached_async(
                safe_query, max_iter, budget, provider=resolved_provider
            )
            if cached is not None:
                cached_response, cached_cost, cached_tokens = cached
                logger.info(
                    f"[/search/stream] cache hit q='{safe_query[:40]}'"
                )
                yield _sse_format({"event": "started", "cached": True})
                yield _sse_format({
                    "event": "done",
                    "cached": True,
                    "result": cached_response,
                    "elapsed": round(_time.time() - t0, 2),
                })
                return

            # R10.5.7 P0-1: 语义缓存兜底 (shingle Jaccard)
            sem_cached = await get_semantic_cached(
                safe_query, max_iter, budget, provider=resolved_provider
            )
            if sem_cached is not None:
                sem_response, _sem_cost, _sem_tokens = sem_cached
                logger.info(
                    f"[/search/stream] SEMANTIC cache hit q='{safe_query[:40]}'"
                )
                yield _sse_format({"event": "started", "cached": True})
                yield _sse_format({
                    "event": "done",
                    "cached": True,
                    "result": sem_response,
                    "elapsed": round(_time.time() - t0, 2),
                })
                return

            yield _sse_format({"event": "started", "cached": False, "max_iter": max_iter})

            accumulated: dict = dict(initial)
            step_count = 0

            try:
                # R10.5 Fix-Timeout: 240s 够单次 8 节点真实 LLM (60-150s),
                # 也允许 max_iter=3 refine 循环. 480s 太长, 用户等 8 分钟没意义,
                # 应让超时 fail fast 提示用户降 max_iter 或换 provider.
                async with asyncio.timeout(240.0):
                    async for chunk in search_graph.astream(initial, stream_mode="updates"):
                        # R10.5 Fix-Cancel-Audit: 协作式取消 — 用户点取消
                        # /search/cancel 会 set() 这个 event, 在 chunk 边界 return.
                        # async generator 里 return 等于停止迭代 + 触发外层 finally,
                        # budget 走 finally 的 return_amount > 0.01 分支归还.
                        if cancel_event.is_set():
                            logger.info(
                                f"[/search/stream] cancelled mid-stream req_id={req_id} "
                                f"after {step_count} nodes"
                            )
                            return_amount = max(0.0, budget - accumulated.get("total_cost_usd", 0.0))
                            return
                        for node_name, state_update in chunk.items():
                            if not isinstance(state_update, dict):
                                continue
                            accumulated.update(state_update)
                            step_count += 1
                            mapped = NODE_NAME_TO_STEP.get(node_name)
                            yield _sse_format({
                                "event": "node_complete",
                                "node": node_name,
                                "step": mapped if mapped is not None else step_count,
                                "elapsed": round(_time.time() - t0, 2),
                                "iteration": accumulated.get("iteration", 0),
                            })
                            # P0-1: 节点级预算硬停止
                            new_total = float(accumulated.get("total_cost_usd", 0.0))
                            budget_limit = float(
                                accumulated.get("budget_limit_usd", float("inf"))
                            )
                            if check_budget(new_total, budget_limit):
                                accumulated["status"] = "budget_exceeded"
                                logger.warning(
                                    f"[/search/stream] P0-1 node-level budget hard stop: "
                                    f"cost=${new_total:.4f} >= limit=${budget_limit:.2f} "
                                    f"after node '{node_name}' (step={step_count})"
                                )
                                try:
                                    yield _sse_format({
                                        "event": "budget_exceeded",
                                        "node": node_name,
                                        "step": mapped if mapped is not None else step_count,
                                        "message": (
                                            f"节点 {node_name} 后累计开销 "
                                            f"${new_total:.4f} 已达/超预算 "
                                            f"${budget_limit:.2f}, 立即中断流水线"
                                        ),
                                        "cost_usd": round(new_total, 4),
                                        "budget_usd": round(budget_limit, 2),
                                    })
                                except Exception:
                                    pass
                                return_amount = max(0.0, budget - new_total)
                                return
            except TimeoutError:
                logger.warning(f"[/search/stream] timed out after 240s, q='{safe_query[:40]}'")
                await _return_budget(budget, user_id=user.user_id)
                return_amount = 0.0
                try:
                    yield _sse_format({
                        "event": "error",
                        "code": "timeout",
                        "message": "搜索超时（>240s）。建议降低 max_iter 或更换 provider（minimax 当前可能限流）。",
                    })
                except Exception:
                    pass
                return
            except asyncio.CancelledError:
                # R10.5 Fix-Cancel: 用户主动取消, 优雅退出而非报"内部错误".
                # 前端 /api/v1/search/cancel → 后端 task.cancel() → 走到这里.
                logger.info(f"[/search/stream] cancelled by user req_id={req_id}")
                await _return_budget(budget, user_id=user.user_id)
                return_amount = 0.0
                # 不发 error 事件 (前端已知道是取消); 但生成器需要 return 触发 finally
                return
            except Exception:
                logger.error("[/search/stream] error", exc_info=True)
                await _return_budget(budget, user_id=user.user_id)
                return_amount = 0.0
                try:
                    yield _sse_format({
                        "event": "error",
                        "code": "internal",
                        "message": "内部服务错误，请稍后重试",
                    })
                except Exception:
                    pass
                return

            elapsed = _time.time() - t0
            actual_cost = float(accumulated.get("total_cost_usd", 0.0))
            diff = budget - actual_cost
            if diff > 0.01:
                return_amount = diff
            else:
                return_amount = 0.0
            response_obj = _build_search_response(accumulated, elapsed)

            # R10.5.9 落地: 双缓存写路径去重 (model_dump 1 次 + 并发)
            response_dict = response_obj.model_dump()
            await _write_search_caches(
                safe_query, max_iter, budget,
                response_dict,
                float(accumulated.get("total_cost_usd", 0.0)),
                int(accumulated.get("total_tokens_used", 0)),
                provider=resolved_provider,
                endpoint="/search/stream",
            )

            yield _sse_format({
                "event": "done",
                "result": response_obj.model_dump(),
                "elapsed": round(elapsed, 2),
            })
        finally:
            # R10.5 Fix-Cancel: 清理 _in_flight_searches, 防止 dict 累积死引用.
            _in_flight_searches.pop(req_id, None)
            _in_flight_searches_age.pop(req_id, None)
            if return_amount > 0.01:
                try:
                    await _return_budget(return_amount, user_id=user.user_id)
                except Exception as return_err:
                    logger.warning(
                        f"[/search/stream] budget return failed (non-fatal): {return_err}"
                    )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ===== R10.5 Fix-P2-4: /api/v1/search /search/stream /search/cancel aliases =====
# Deprecated — 旧客户端继续用 /search; 新客户端用 /api/v1/search.
# 当未来 v2 引入时, /api/v1/* 路径继续服务旧逻辑, 旧 /search 路径最终下线.
app.add_api_route(
    "/api/v1/search", search, methods=["POST"],
    response_model=SearchResponse,
)
app.add_api_route(
    "/api/v1/search/stream", search_stream, methods=["GET"],
)
app.add_api_route(
    "/api/v1/search/cancel", cancel_search, methods=["POST"],
)


# ===== R10.5.20: Runtime Mode 切换 (前端 UI 控制 mock/real) =====

from pydantic import BaseModel as _BaseModel
from backend.utils.runtime_mode import (
    get_runtime_mode,
    set_runtime_mode,
    is_runtime_mock,
)


class RuntimeModeResponse(_BaseModel):
    mode: str  # "mock" | "real"
    source: str  # "runtime" (前端切了) | "env" (env LLM_MOCK/API_MOCK 兜底)


class RuntimeModeRequest(_BaseModel):
    mode: str  # "mock" | "real" | "auto"


async def get_runtime_mode_endpoint() -> RuntimeModeResponse:
    """返回当前 runtime mode + 来源 (env / runtime).

    GET 公开 — 不影响安全, 前端启动时拉取方便, 不暴露任何用户态.
    """
    rt_mode = get_runtime_mode()
    if rt_mode in ("mock", "real"):
        return RuntimeModeResponse(mode=rt_mode, source="runtime")
    # auto: 走 env 兜底, 告诉前端当前是 mock 还是 real
    return RuntimeModeResponse(
        mode="mock" if is_runtime_mock() else "real",
        source="env",
    )


async def set_runtime_mode_endpoint(
    req: RuntimeModeRequest,
    _admin: User = Depends(require_admin),  # R10.5.21 鉴权
) -> RuntimeModeResponse:
    """切换 runtime mode. 'auto' = 恢复 env 行为.

    R10.5.20: 进程级 (per-worker) 状态, 4-worker Gunicorn 部署下每个 worker
    独立 (跟 circuit_breaker.py 同模型), 用户切到 mock 后只有 1/N 请求
    走 mock. 短期接受, R11+ 切到 Redis. 文档化在 runtime_mode.py 模块头.

    R10.5.21 (J.txt + K.txt 审计 #1): 必须 admin 身份. 没配置 ADMIN_USER_IDS
    时所有 POST 默认 403 拒绝 (fail-closed). 配置示例 (.env):
        ADMIN_USER_IDS=u_abc123,u_def456
    """
    if req.mode not in ("mock", "real", "auto"):
        raise HTTPException(status_code=400, detail=f"mode 必须是 mock/real/auto, 收到 {req.mode!r}")
    set_runtime_mode(req.mode)  # type: ignore[arg-type]
    logger.info(f"[admin] runtime_mode → {req.mode} (by {_admin.user_id[:8]}***)")
    return RuntimeModeResponse(
        mode=req.mode,  # type: ignore[arg-type]
        source="runtime",
    )


app.add_api_route(
    "/api/v1/admin/runtime-mode", get_runtime_mode_endpoint, methods=["GET"],
)
app.add_api_route(
    "/api/v1/admin/runtime-mode", set_runtime_mode_endpoint, methods=["POST"],
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
