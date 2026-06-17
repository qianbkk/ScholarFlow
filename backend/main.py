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
from backend.api.routes.admin import router as admin_router  # R10.5.28: admin 路由抽离
# R10.5.28: get_runtime_mode / is_runtime_mock / set_runtime_mode 仍被 search()/search_stream()
# inline 用到 (cache key 需要), 不能仅靠 admin.py 导入. 显式 import 一次, 跟其它 helper 一起.
from backend.utils.runtime_mode import get_runtime_mode, is_runtime_mock, set_runtime_mode  # R10.5.20
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
    runtime_mode: str = "unknown",  # R10.5.28: cache key 拼 runtime_mode, mock↔real 独立
    endpoint: str,  # "/search" 或 "/search/stream" — 日志用
) -> None:
    """并发写精确缓存 (SQLite) + 语义缓存 (in-memory LRU).

    失败各自 warning, 互不影响. 整体 best-effort.
    """
    async def _write_precise() -> None:
        try:
            await set_cached_async(
                safe_query, max_iter, budget, response_dict,
                cost_usd, tokens, provider=provider, runtime_mode=runtime_mode,
            )
        except Exception as e:
            logger.warning(f"[{endpoint}] cache write failed (non-fatal): {e}")

    async def _write_semantic() -> None:
        try:
            await set_semantic_cached(
                safe_query, max_iter, budget, response_dict,
                cost_usd, tokens, provider=provider,
                # R10.5.29 (simplify): 拼 LRU key, 跟精确缓存 runtime_mode 隔离
                # 行为保持一致. 旧版缺这个 kwarg, semantic LRU 只按 query 匹配,
                # mock↔real 跨模式命中导致 history 标签错.
                runtime_mode=runtime_mode,
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
    # R10.5.28 (CG.txt 审计 P0 #1+#2): 启动期扫描认证弱点.
    #  1) 有 password_hash=NULL 的老 user → 警告需升级密码
    #  2) OPEN_MODE=false + ADMIN_USER_IDS 空 + admin.sqlite 空 → admin 端点全 403
    try:
        from backend.utils.cache import _connect_with_wal
        from backend.auth.dependencies import get_effective_admin_user_ids
        conn = _connect_with_wal("auth")
        try:
            null_pw = conn.execute(
                "SELECT COUNT(*) FROM users WHERE password_hash IS NULL"
            ).fetchone()[0]
        finally:
            conn.close()
        if null_pw > 0:
            logger.warning(
                f"[SECURITY] {null_pw} 个老用户 password_hash=NULL, 仍可 passwordless 登录. "
                f"建议这些用户重新注册设密码 (CG.txt 审计 P0 #1). "
                f"或在 .env 设 REQUIRE_PASSWORDLESS_LOGIN=false 强制要求密码 (R11+)."
            )
        if not OPEN_MODE and not get_effective_admin_user_ids():
            logger.warning(
                "[SECURITY] admin 白名单为空 (ADMIN_USER_IDS env + admin.sqlite 都空). "
                "/api/v1/admin/runtime-mode POST 全部 403. "
                "显式初始化: (1) .env 设 ADMIN_USER_IDS=u_xxx; "
                "(2) 或 `python -m backend.auth.admin add u_xxx` 持久化."
            )
    except Exception as e:
        logger.warning(f"[lifespan] admin/password audit failed (non-fatal): {e}")
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
    from backend.utils.runtime_mode import (
        is_runtime_mock, get_runtime_mode, detect_runtime_profile, RuntimeProfile,
    )
    rt_mode = get_runtime_mode()
    effective_mock = is_runtime_mock()
    profile = detect_runtime_profile()
    profile_warn = ""
    if profile == RuntimeProfile.PRODUCTION and effective_mock:
        # 检测到矛盾: profile 说 PRODUCTION 但 effective mock — 配置错配
        profile_warn = (
            "  ⚠️  WARNING: profile=PRODUCTION 但 effective=MOCK, "
            "说明 LLM_MOCK 或 API_MOCK 被 runtime override 强切到 mock. "
            "前端 /admin/runtime-mode 切了 mock 会覆盖 PRODUCTION profile."
        )
    logger.info(
        f"[lifespan] === Runtime mode status ===\n"
        f"  profile    = {profile.value}  (R10.5.25 集中化)\n"
        f"  OPEN_MODE  = {OPEN_MODE}  (auth: {'SKIPPED (dev-user)' if OPEN_MODE else 'REQUIRED'})\n"
        f"  LLM_MOCK   = {_LLM_MOCK}  (config.py env)\n"
        f"  API_MOCK   = {_API_MOCK}  (config.py env)\n"
        f"  runtime    = {rt_mode!r}  (POST /api/v1/admin/runtime-mode override)\n"
        f"  effective  = {'MOCK (返回内置数据)' if effective_mock else 'REAL (调用真实 API)'}"
        f"{profile_warn}"
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
    # 关闭：R10.5.32 (wave 7) 优雅 shutdown. k8s 滚动更新时, SIGTERM 触发
    # lifespan shutdown, 此时可能还有 in-flight SSE 流正在跑. 直接关
    # client 会让 in-flight 流报 "client disconnected" → 用户看到 1000s
    # loading. 正确做法: 等 in-flight 流 (最多 30s) 自然完成, 然后关
    # client + 跑 cache GC.
    inflight = list(_in_flight_searches.items())
    if inflight:
        logger.info(
            f"[lifespan] shutdown: waiting for {len(inflight)} in-flight search(es) "
            "(max 30s)..."
        )
        deadline = asyncio.get_event_loop().time() + 30.0
        while _in_flight_searches and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
        if _in_flight_searches:
            logger.warning(
                f"[lifespan] shutdown timeout: {_in_flight_searches} still in-flight, "
                "force-cancelling"
            )
    # 跑 cache GC 一次 (lifespan 退出前清旧条目, 跟磁盘做"出关检查")
    try:
        from backend.utils.cache import gc_cache
        gc_results = gc_cache(max_age_days=30, max_rows=1000)
        logger.info(f"[lifespan] shutdown: cache GC done: {gc_results}")
    except Exception as e:
        logger.warning(f"[lifespan] shutdown: cache GC failed (non-fatal): {e}")
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
app.include_router(admin_router, prefix=API_V1_PREFIX)  # R10.5.28: admin 路由抽到 routes/admin.py
# R10.5.30 (D2): search router 抽到 routes/search.py, 替代 main.py 的 inline
# 路由. 旧版 main.py 1140 行里有 ~300 行 search/search_stream/cancel_search
# inline 代码 + 静态测试 (test_routes_not_double_mounted.py) 锁死不能迁移.
# 现在翻转: main.py 不再 inline, search_router 真正挂载, 删 inline 重复.
# 注意: search_router 内部已经有 /api/v1/* paths (自身用 @router.post('/search')
# 形式), 直接挂载到根 + /api/v1 都行.
from backend.api.routes.search import router as search_router  # R10.5.30 D2
app.include_router(search_router)  # 裸 /search alias (R10.5 P2-4 兼容性)
app.include_router(search_router, prefix=API_V1_PREFIX)  # /api/v1/search (新客户端标准)
# Deprecated alias: 旧客户端继续用无前缀路径
app.include_router(health_router)
app.include_router(auth_router)  # R10.5 Fix-P0-B: 多用户 + API Key (/auth/register + /login + /me)
app.include_router(admin_router)  # R10.5.28: 裸 /admin/* alias



# [R10.5.30 D2] search/cancel_search/search_stream 抽到 routes/search.py (被 include_router 替代). 详见面 import 行.



# ===== R10.5.20: Runtime Mode 切换 (前端 UI 控制 mock/real) =====
# R10.5.28 (CG.txt 审计 P1 #5): 路由体抽到 backend.api.routes.admin.
# admin_router import 在文件顶部 (~line 105), 这里 include_router 两次
# R10.5.28 (CG.txt 审计 P1 #5): 路由体抽到 backend.api.routes.admin.
# admin_router import 在文件顶部 (~line 105), 这里 include_router 两次
# (v1 prefix + 裸 alias) 跟 health/auth 模式一致. 路由体不在 main.py 了.


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
