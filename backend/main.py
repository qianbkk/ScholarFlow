"""
ScholarFlow FastAPI 入口
========================
提供 /search 和 /health 接口
"""
import asyncio
import json
import logging
import os
import re
import sys
import time as _time
from contextlib import asynccontextmanager
from typing import Optional

# 让 uvicorn 直接启动时也能找到 backend 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.workflow.graph import search_graph
from backend.api import semantic_scholar as _ss_mod
from backend.api import openalex as _oa_mod
from backend.utils.proxy import get_proxy  # 预热代理缓存
from backend.utils.sanitize import sanitize_query  # VULN-001
from backend.utils.cache import get_cached_async, set_cached_async  # H4: result cache (async, non-blocking)
from backend.utils.observability import (  # Round 2 PERF-007: 全链路 request_id
    new_request_id,
    set_request_id,
    get_request_id,
    setup_logging,
)
from backend.utils.budget_guard import (  # P0-1: 节点级预算硬停止
    BudgetExceededError,
    check_budget,
)
from backend.config import (
    BUDGET_LIMIT_USD,
    MAX_SEARCH_ITERATIONS,
    LLM_PROVIDER,
    DEEPSEEK_API_KEY,
    get_provider_config,
)
from backend.middleware import install_security  # Round 5 M-3: HTTP 安全头 + TrustedHost

# NEW-002 修复：logger 移至模块级
logger = logging.getLogger(__name__)


# ===== Provider 路由元数据（用户可选 LLM）=====
# 给前端 /providers 端点用的展示元数据。
# has_key 来自对应 *_API_KEY 环境变量 — 没有 key 的 provider 不在选择列表里。
# DeepSeek 走 OpenAI 协议（不走 get_provider_config），单独处理。
_PROVIDER_META = {
    "kimi": {
        "name": "Kimi (Moonshot)",
        "flagship_model": "kimi-k2.5",
        "fast_model": "kimi-k2.5",
    },
    "glm": {
        "name": "GLM (智谱)",
        "flagship_model": "glm-4.6",
        "fast_model": "glm-4.6-air",
    },
    "minimax": {
        "name": "MiniMax",
        "flagship_model": "MiniMax-M3",
        "fast_model": "MiniMax-M2.7",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "flagship_model": "claude-sonnet-4-6",
        "fast_model": "claude-haiku-4-5-20251001",
    },
    "deepseek": {
        "name": "DeepSeek",
        "flagship_model": "deepseek-reasoner",
        "fast_model": "deepseek-chat",
    },
}


# ===== Provider 健康检查缓存（key 真实可用性，非仅 env 非空）=====
# 用户在 .env 填了 Kimi/GLM key 但实际可能 401 失效。仅检查 env 非空会让
# /providers 返回误导性的 has_key=true，前端选择后真实调用失败 → 静默
# fallback 到 mock，用户看到"当前为 mock 模式"。这里在 lifespan + 定期
# 用最小 API 调用 (max_tokens=1) 验证 key, 缓存结果。
_PROVIDER_HEALTH_CACHE: dict[str, tuple[bool, float]] = {}
_PROVIDER_HEALTH_TTL_SECONDS = 300.0  # 5 min — 比 startup 一次更可靠


async def _verify_provider_key(provider_id: str) -> bool:
    """对单个 provider 做最小 API 调用验证 key 真实有效。

    Anthropic 协议: messages.create(max_tokens=1, 1 token prompt)
    OpenAI 协议 (DeepSeek): chat.completions.create(max_tokens=1)

    Returns:
        True  if API 调用成功 (任意 content / finish_reason)
        False if 401/403/网络错误/超时
    """
    if provider_id == "deepseek":
        try:
            from openai import AsyncOpenAI
            from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
            if not DEEPSEEK_API_KEY:
                return False
            client = AsyncOpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
                timeout=10.0,
            )
            resp = await client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=1,
                messages=[{"role": "user", "content": "ok"}],
            )
            return bool(resp.choices)
        except Exception:
            return False
    else:
        try:
            import anthropic
            from backend.utils.llm_client import _get_anthropic_client
            client = _get_anthropic_client(provider_id)
            if client is None:
                return False
            # Anthropic SDK 不暴露 ping, 用最小 messages.create 验证
            # 选 fast_model (更快更便宜)
            cfg = get_provider_config(provider_id)
            fast_model = cfg.get("fast_model") or cfg.get("model", "")
            if not fast_model:
                return False
            resp = await client.messages.create(
                model=fast_model,
                max_tokens=1,
                messages=[{"role": "user", "content": "."}],
            )
            # 任意正常 stop_reason 都算通过 (包括 end_turn/max_tokens/refusal)
            return getattr(resp, "stop_reason", None) is not None
        except Exception:
            return False


def _get_providers_with_keys() -> list[dict]:
    """返回所有可用的 provider 列表（含 has_key 状态）。

    has_key 语义:
      * env var 非空 且 健康检查最近一次通过 → True
      * env var 为空 或 健康检查失败 → False
      * 健康检查尚未运行 (启动几秒内) → 用 env 非空作 optimistic 估计

    健康检查在 lifespan 启动时跑一次，之后每 5 分钟刷新一次。
    """
    out: list[dict] = []
    for pid, meta in _PROVIDER_META.items():
        # 1) 基础检查：env var 是否配置
        if pid == "deepseek":
            env_key_present = bool(DEEPSEEK_API_KEY)
        else:
            cfg = get_provider_config(pid)
            env_key_present = bool(cfg.get("enabled", False))

        # 2) 健康检查缓存（如果最新）
        cached = _PROVIDER_HEALTH_CACHE.get(pid)
        if cached and (_time.time() - cached[1]) < _PROVIDER_HEALTH_TTL_SECONDS:
            verified = cached[0]
        else:
            verified = None  # 未检查 或 缓存过期

        # 3) 决定 has_key:
        #    - 缓存有效 → 用缓存
        #    - 缓存无效/无 → 启动后用 env 估计；启动前 (lifespan 未跑完) 总是 None
        if verified is not None:
            has_key = env_key_present and verified
        else:
            # 启动乐观估计：env 非空就 True（但前端可加 has_verified 字段）
            has_key = env_key_present

        out.append({
            "id": pid,
            "name": meta["name"],
            "flagship_model": meta["flagship_model"],
            "fast_model": meta["fast_model"],
            "has_key": has_key,
            "verified": verified,  # True/False/None (None = 未检查)
        })
    return out


async def _refresh_provider_health_cache() -> None:
    """后台任务：刷新所有 provider 的真实 key 可用性。"""
    pids = list(_PROVIDER_META.keys())
    for pid in pids:
        try:
            ok = await _verify_provider_key(pid)
            _PROVIDER_HEALTH_CACHE[pid] = (ok, _time.time())
            logger.info(f"[providers] {pid} verified={ok}")
        except Exception as e:
            _PROVIDER_HEALTH_CACHE[pid] = (False, _time.time())
            logger.warning(f"[providers] {pid} verify failed: {e}")


def _resolve_provider(provider: Optional[str]) -> str:
    """解析并校验 provider；合法则返回小写 id，否则 raise 400。

    规则：
      * None 或空字符串 → 默认 LLM_PROVIDER（来自 .env）
      * 在已配置 key 的 provider 列表里 → 返回该 id
      * 其他 → 400 (含可用的 provider 列表)
    """
    candidates = _get_providers_with_keys()
    valid_ids = {p["id"] for p in candidates}
    if not provider:
        return LLM_PROVIDER.lower()
    provider = provider.strip().lower()
    if provider not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 provider: {provider!r}. 可用: {sorted(valid_ids)}",
        )
    return provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动期预热代理缓存，关闭期释放连接池。"""
    # Round 2 PERF-007: 启动时绑定 RequestIdFilter 到根 logger,
    # 让所有子 logger 都自动带上 request_id 字段。
    setup_logging()
    # 启动：预热代理检测（后台线程，避免阻塞事件循环）
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_proxy)
    logger.info("[lifespan] proxy cache pre-warmed, HTTP pool ready")
    # 启动：异步刷新 provider 健康检查 (background task)
    # 不 await — 不阻塞 startup;首个 /providers 请求会等待结果返回
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


# Round 2 PERF-007: 全链路 request_id 追踪, middleware + contextvars 注入 logger, 端到端可观测性
# Round 4 R1: X-Request-ID header 加长度 + charset 校验, 防止恶意 10MB header 撑爆日志
_MAX_RID_LEN = 128
_RID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


@app.middleware("http")
async def request_id_middleware(request, call_next):
    """为每个 HTTP 请求注入 request_id。

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
    # 只暴露真正用到的 GET（health/stream）+ POST（search）。
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept", "Cache-Control"],
)

# Round 5 M-3: HTTP 安全头 (X-Content-Type-Options/X-Frame-Options/CSP/HSTS 等 7 个)
# + TrustedHostMiddleware (Host header 注入防护)。在 CORS 之后注册,
# 让所有响应(含 CORS 错误)都带安全头。ALLOWED_HOSTS env 可收紧 (默认 "*" 开发友好)。
install_security(app)


# ===== Rate limiting + global budget (VULN-002) =====
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ===== Round 5 S-3: 自定义 422 异常处理器, 不回显用户 input =====
# 默认 FastAPI 在 RequestValidationError 时把用户 input 全文回显到响应 body,
# 攻击者可借此向日志注入 ANSI / 控制字符 / 大量冗长字段, 也泄露隐私 (query
# 字符串中可能含 PII 或机构内部检索词)。这里只回显错误类型, 不回显 input。
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

# 全局每小时预算计数器（H2 修复：迁移到 SQLite WAL — 多 worker 原子性）
# 旧版用进程内 dict + .budget_state.json 文件，4-worker Gunicorn 部署下：
#   - 4 个独立进程各持一份 counter，实际预算 × 4
#   - .json 文件非原子写入，4 进程同时写时可能损坏
# 新版：在已有 cache DB（WAL 模式）增加 budget_state 表，跨进程 / 跨 worker 共享。
GLOBAL_HOURLY_BUDGET = float(os.getenv("GLOBAL_HOURLY_BUDGET", "50.0"))
_budget_lock = asyncio.Lock()
# 进程内只缓存 reset_ts（避免每次都读 DB）；total 始终从 DB 读最新值
_budget_reset_ts: float = _time.time()


def _init_budget_table() -> None:
    """初始化 budget_state 表 + 插入 global 行（H2 修复：复用 cache DB 的 WAL 连接）。

    幂等：多次调用只会创建一次表、只插入一次 global 行（INSERT OR IGNORE）。
    """
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_state (
                key TEXT PRIMARY KEY,
                total REAL NOT NULL,
                reset_ts REAL NOT NULL
            )
            """
        )
        # 默认行：global 计数器。INSERT OR IGNORE 避免覆盖现有数据。
        conn.execute(
            "INSERT OR IGNORE INTO budget_state (key, total, reset_ts) VALUES ('global', 0.0, ?)",
            (_time.time(),),
        )
        conn.commit()
    finally:
        conn.close()


def _load_budget_from_db() -> tuple[float, float]:
    """从 SQLite 读取 (total, reset_ts)。无行时返回 (0.0, now)。"""
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        row = conn.execute(
            "SELECT total, reset_ts FROM budget_state WHERE key='global'"
        ).fetchone()
        if row is None:
            return 0.0, _time.time()
        return float(row[0]), float(row[1])
    finally:
        conn.close()


def _save_budget_to_db(total: float, reset_ts: float) -> None:
    """把 (total, reset_ts) 持久化到 SQLite（H2 修复：跨进程原子）。

    兼容性: 仍接受 (total, reset_ts) 两参签名,内部封装 BEGIN IMMEDIATE 事务。
    详细事务包裹逻辑见 _check_and_reserve_budget / _return_budget。
    """
    from backend.utils.cache import _connect_with_wal
    conn = _connect_with_wal()
    try:
        # BEGIN IMMEDIATE: 立即获取写锁,防止多 worker 间 TOCTOU 竞态
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE budget_state SET total=?, reset_ts=? WHERE key='global'",
            (total, reset_ts),
        )
        conn.commit()
    finally:
        conn.close()


def _load_budget_state() -> None:
    """启动时从 SQLite 恢复预算计数。无行/损坏时保持默认 (0, now)。"""
    global _budget_reset_ts
    try:
        _init_budget_table()
        total, ts = _load_budget_from_db()
        # 若记录的窗口已过期，则丢弃
        if _time.time() - ts > 3600:
            _save_budget_to_db(0.0, _time.time())
            _budget_reset_ts = _time.time()
            total = 0.0
        else:
            _budget_reset_ts = ts
        logger.info(
            f"[budget] loaded persisted state: total=${total:.4f}, "
            f"reset_ts={_budget_reset_ts:.0f}"
        )
    except Exception as e:
        logger.warning(f"[budget] failed to load state: {e}, starting fresh")


# 启动时尝试恢复
_load_budget_state()


async def _check_and_reserve_budget(estimated_cost: float) -> None:
    """原子化地"检查 + 预留"全局预算（H1+H2+TOCTOU 修复）。

    H1: 整个 check + reserve 在 `_budget_lock` 临界区内完成，关闭进程内 TOCTOU 竞态。
    H2: counter 状态存储在 SQLite WAL 中（budget_state 表），跨 worker 进程原子。
    TOCTOU fix: 读-改-写 全程在 `BEGIN IMMEDIATE` 事务中，
        防止多 worker 进程间 SQLite 层面的 TOCTOU 竞态(普通 BEGIN 拿到的是
        共享锁,第二个 worker 进来时读到的仍是旧 total,会超额累加)。
        BEGIN IMMEDIATE 立即获取写锁,串行化整个 critical section。

    Args:
        estimated_cost: 本次请求愿意预留的最大开销（= `req.budget`，即用户上限）。
    """
    global _budget_reset_ts
    async with _budget_lock:
        # 从 DB 读最新值（避免任何缓存导致跨进程看到的旧 total）
        total, reset_ts = _load_budget_from_db()
        now = _time.time()
        if now - reset_ts > 3600:
            total = 0.0
            reset_ts = now
        if total + estimated_cost > GLOBAL_HOURLY_BUDGET:
            raise HTTPException(503, detail="全局预算上限已达，请稍后重试")
        # 在锁内完成预留 + 持久化（下一个 worker 读到的就是新 total）
        new_total = total + estimated_cost
        _save_budget_to_db(new_total, reset_ts)
        # 进程内缓存 reset_ts，避免每个请求都读 DB
        _budget_reset_ts = reset_ts


async def _return_budget(amount: float) -> None:
    """归还实际开销与预留之间的差额(防止过度预留耗尽全局预算)。

    入口 `_check_and_reserve_budget` 预留的是 `req.budget`(用户上限),
    但实际 `total_cost_usd` 通常远低于上限。差额若不归还,会导致
    后续请求被错误拒绝(503)。这里在请求结束时归还差额。

    实现: 加 asyncio.Lock + BEGIN IMMEDIATE,与 reserve 路径一致,
    保证多 worker 间的 read-modify-write 原子性。
    """
    if amount <= 0:
        return
    global _budget_reset_ts
    async with _budget_lock:
        from backend.utils.cache import _connect_with_wal
        conn = _connect_with_wal()
        try:
            conn.execute("BEGIN IMMEDIATE")  # 立即获取写锁,防多 worker TOCTOU
            row = conn.execute(
                "SELECT total, reset_ts FROM budget_state WHERE key='global'"
            ).fetchone()
            if row is None:
                return  # 表未初始化,无须归还
            total = float(row[0])
            reset_ts = float(row[1])
            # 边界保护: 不能减到负数
            new_total = max(0.0, total - amount)
            conn.execute(
                "UPDATE budget_state SET total=?, reset_ts=? WHERE key='global'",
                (new_total, reset_ts),
            )
            conn.commit()
            _budget_reset_ts = reset_ts
        finally:
            conn.close()


# ===== Request / Response Models =====

def _make_initial_state(
    safe_query: str,
    max_iterations: int,
    budget: float,
    provider: str,
    status: str = "decomposing",
) -> dict:
    """构造 LangGraph SearchState 初始 dict.

    Round 4 C2: 抽出来避免 /search 和 /search/stream 两处复制, 杜绝字段漂移。
    """
    return {
        "original_query": safe_query,
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "expanded_paper_ids": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": max_iterations,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": budget,
        "model_usage": {},
        "status": status,
        "error": None,
        "provider": provider,
        "request_id": get_request_id(),
    }


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="研究查询（中英文均可）")
    budget: float = Field(default=BUDGET_LIMIT_USD, ge=0.1, le=20.0, description="单次预算上限 USD")
    max_iterations: int = Field(default=MAX_SEARCH_ITERATIONS, ge=1, le=5, description="最大迭代轮次")
    # 可选 LLM provider — None/空 → 用 LLM_PROVIDER env；其他 → 必须在 GET /providers 中 has_key=true
    provider: Optional[str] = Field(default=None, max_length=64, description="LLM provider id (kimi/glm/minimax/anthropic/deepseek)")


class SearchCancelRequest(BaseModel):
    """用户主动取消 in-flight 搜索的请求 (Round 4 U2 配套)。"""
    request_id: Optional[str] = None


class PaperResult(BaseModel):
    paper_id: str = ""
    title: str = ""
    abstract: str = ""
    year: int = 0
    authors: list[str] = []
    citation_count: int = 0
    venue: str = ""
    url: str = ""
    source: str = ""
    is_expanded: bool = False
    relevance_score: float = 0.0
    authority_score: float = 0.0
    consistency_score: float = 0.0
    final_score: float = 0.0


class SearchResponse(BaseModel):
    report: str
    ranked_papers: list[PaperResult]
    citation_graph: dict
    total_cost_usd: float
    total_tokens_used: int
    # Round 5 M-4: model_usage 改名 + 白名单 — 去除 cost + provider 内部名泄露
    # 旧字段名 model_usage 直接把 llm_client 的内部结构透出,含 "MiniMax-M3"、
    # "(fallback to mock)" 后缀、cost_usd 等敏感内部信息。改为 model_usage_summary,
    # 只保留 { model_name: { tokens: int } } 干净结构,既满足前端展示,又避免
    # provider 内部实现细节 (provider name / cost) 泄露到 API 响应。
    model_usage_summary: dict = Field(default_factory=dict)
    iteration: int
    status: str
    elapsed_seconds: float = 0.0
    # Round 5 M-1: 顶层信号 — 闭环 Round 4 degraded banner.
    # is_degraded_response: 至少有一篇论文是 fallback 来的 (search agent fallback 触发)
    # fallback_paper_count:  fallback 论文计数 (供前端 banner 显式展示)
    is_degraded_response: bool = False
    fallback_paper_count: int = 0


# ===== Routes =====

@app.get("/health")
async def health():
    """健康检查。"""
    return {
        "status": "ok",
        "service": "ScholarFlow",
        "version": "1.0.0",
    }


@app.get("/providers")
async def list_providers():
    """返回所有可用 LLM provider 列表（含 has_key 状态 + 默认 provider）。

    前端模型选择器用此端点渲染下拉 — 只展示 has_key=true 的 provider。
    """
    return {
        "default_provider": LLM_PROVIDER.lower(),
        "providers": _get_providers_with_keys(),
    }


@app.post("/search", response_model=SearchResponse)
@limiter.limit("5/minute;20/hour")
async def search(req: SearchRequest, request: Request):
    """主搜索接口：触发完整 8 节点流水线。"""
    # VULN-001 Layer 0: 入口处净化用户 query (Round 2 CRITICAL-002+PERF-002: 移到
    # 预算预留之前, 避免输入校验失败时白白消耗预算配额 — 失败请求不消耗预算)
    try:
        safe_query = sanitize_query(req.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    # 校验 provider（如有）；无效或无 key → 400 (同样在预算预留前, 失败不消耗预算)
    provider = _resolve_provider(req.provider)

    # VULN-002: 全局每小时预算闸门（H1 修复：原子化 check-and-reserve）
    # Round 2 CRITICAL-002+PERF-002: reserve 在 sanitize/provider 之后, 然后
    # try/finally 兜底, 任何异常/超时/取消/缓存命中路径都确保预算归还
    await _check_and_reserve_budget(req.budget)
    budget_reserved = True  # try/finally 兜底标志

    initial = _make_initial_state(
        safe_query, req.max_iterations, req.budget, provider
    )

    import time
    t0 = time.time()
    # Round 2 CRITICAL-002+PERF-002: finally 用 return_amount 决定归还额度
    # 默认 req.budget (异常/超时/缓存命中); 成功路径更新为 (budget - actual_cost)
    return_amount = req.budget

    try:
        # 缓存命中：直接返回上次结果（避免重复跑付费流水线）
        # H4 修复：用 async 版本，SQLite I/O 走 to_thread、retry 退避走 asyncio.sleep
        # Round 2 审计 (CRITICAL-001): cache_key 函数已加 provider 参数, 调用点必须传
        # 以隔离跨 provider 的同 query 缓存,避免 kimi 缓存被 glm/anthropic 误命中
        cached = await get_cached_async(safe_query, req.max_iterations, req.budget, provider=provider)
        if cached is not None:
            cached_response, cached_cost, cached_tokens = cached
            logger.info(
                f"[/search] cache hit q='{safe_query[:40]}' "
                f"cost=${cached_cost:.4f} tokens={cached_tokens}"
            )
            # 缓存命中: 本次未消耗 LLM, 全数归还 (return_amount 保持 = req.budget)
            return SearchResponse(**cached_response)

        # 240s 上限：real 模式下 8 个 LLM 调用 + 双源检索 + 引文扩展通常需 100-180s,
        # 120s 在 query 复杂时会过早超时(Phase 3 验证: AlphaFold 查询实际 135s)
        # P0-1: 包 try/except BudgetExceededError — 节点内主动 raise 时的兜底
        # (当前 graph 节点不会主动 raise, 但保留扩展点, 未来 cost_tracker
        # 节点可在 cost >= budget 时 raise 让主流程走 budget_exceeded 分支)
        try:
            final = await asyncio.wait_for(search_graph.ainvoke(initial), timeout=240.0)
        except BudgetExceededError as bee:
            elapsed = time.time() - t0
            logger.warning(
                f"[/search] BudgetExceededError from graph: cost=${bee.cost:.4f} "
                f">= limit=${bee.limit:.2f} node={bee.node}"
            )
            # 已花 bee.cost, 剩余预算全归还 (return_amount 由 finally 处理)
            return_amount = max(0.0, req.budget - bee.cost)
            return SearchResponse(
                report=(
                    f"搜索因预算超限中止: 累计开销 ${bee.cost:.4f} 已达/超过 "
                    f"单次预算 ${bee.limit:.2f}。"
                ),
                ranked_papers=[],
                citation_graph={},
                total_cost_usd=round(bee.cost, 4),
                total_tokens_used=0,
                model_usage={},
                iteration=0,
                status="budget_exceeded",
                elapsed_seconds=round(elapsed, 2),
            )
        elapsed = time.time() - t0
        # H1 修复：预算已在入口处原子化预留（_check_and_reserve_budget），
        # 实际开销 ≤ req.budget（用户的 max），无需再次累加。
        # 预算归还: 实际花费通常远低于 req.budget, 归还差额避免过度预留
        # 阻塞后续请求 (e.g. 预留 2.0 / 实花 0.3 → 立即还 1.7)
        actual_cost = float(final.get("total_cost_usd", 0.0))
        # P0-1 兜底: 即使 graph 没主动 raise, 出口处再核一次 (防御性)
        # 正常 SSE 路径已实时硬停; 此处保护 /search 同步路径
        budget_limit_state = float(final.get("budget_limit_usd", req.budget))
        if check_budget(actual_cost, budget_limit_state):
            logger.warning(
                f"[/search] final cost ${actual_cost:.4f} >= budget "
                f"${budget_limit_state:.2f}, marking budget_exceeded"
            )
            # 不改 actual_cost, 但 status 标记
            final = dict(final)
            final["status"] = "budget_exceeded"
        diff = req.budget - actual_cost
        if diff > 0.01:  # $0.01 阈值避免无意义小数运算
            return_amount = diff
        else:
            return_amount = 0.0

        # Round 5 M-1: 计算顶层 is_degraded 信号 (闭环 Round 4 banner)
        ranked = final.get("ranked_papers", [])
        fallback_count = sum(1 for p in ranked if p.get("is_fallback", False))
        is_degraded = fallback_count > 0
        # Round 5 M-4: model_usage 白名单 — 去除 cost + provider 内部名
        # 只保留 { model: { tokens } }, 去掉 " (fallback to mock)" 后缀
        model_usage_raw = final.get("model_usage") or {}
        model_usage_summary = {
            (k.split(" (")[0]): {"tokens": int((v or {}).get("tokens", 0))}
            for k, v in model_usage_raw.items()
        }
        response_obj = SearchResponse(
            report=final.get("report", ""),
            ranked_papers=[PaperResult(**p) for p in final.get("ranked_papers", [])[:25]],
            citation_graph=final.get("citation_graph", {}),
            total_cost_usd=round(final.get("total_cost_usd", 0.0), 4),
            total_tokens_used=final.get("total_tokens_used", 0),
            model_usage_summary=model_usage_summary,
            iteration=final.get("iteration", 0),
            status=final.get("status", "done"),
            elapsed_seconds=round(elapsed, 2),
            is_degraded_response=is_degraded,
            fallback_paper_count=fallback_count,
        )

        # 写入缓存（供下次同 query 复用，TTL 默认 24h）
        # H4 修复：用 async 版本
        # Round 2 审计 (CRITICAL-001): set_cached_async 也必须传 provider 保持 read/write 对称
        try:
            await set_cached_async(
                safe_query,
                req.max_iterations,
                req.budget,
                response_obj.model_dump(),
                float(final.get("total_cost_usd", 0.0)),
                int(final.get("total_tokens_used", 0)),
                provider=provider,
            )
        except Exception as cache_err:
            logger.warning(f"[/search] cache write failed (non-fatal): {cache_err}")

        return response_obj
    except asyncio.TimeoutError:
        # 必须在 except Exception 之前（TimeoutError 是 Exception 子类，会被吞掉）
        logger.warning("[/search] timed out after 240s")
        # 超时: 几乎没产生成本(只跑了部分节点), 全数归还 (return_amount 保持 = req.budget)
        raise HTTPException(
            status_code=504,
            detail="搜索超时（>240s）。建议缩小查询范围或降低 max_iterations。",
        )
    except Exception as e:
        # 仅服务端日志记详情，HTTP body 不暴露内部信息（VULN-002 修复）
        logger.error("[/search] error", exc_info=True)
        # 异常: return_amount 保持 = req.budget (全还)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")
    finally:
        # Round 2 CRITICAL-002+PERF-002: 兜底归还, 确保任何未显式 return budget 的路径都归还
        if budget_reserved and return_amount > 0.01:
            try:
                await _return_budget(return_amount)
            except Exception as return_err:
                logger.warning(f"[/search] budget return failed (non-fatal): {return_err}")


@app.get("/")
async def root():
    return {
        "service": "ScholarFlow",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["GET /health", "GET /providers", "POST /search", "GET /search/stream"],
    }


@app.post("/search/cancel")
async def cancel_search(req: SearchCancelRequest):
    """用户主动取消进行中的搜索 (Round 4 U2 配套)。

    当前实现: 仅记日志, 真正中断在 client disconnect 时已经走 SSE 的 try/finally。
    未来可在 in-flight task table 中查 request_id → task.cancel()。
    """
    logger.info(f"[/search/cancel] request_id={req.request_id} received")
    return {"cancelled": True, "request_id": req.request_id}


# ===== SSE streaming endpoint (real-time progress) =====
#
# 设计要点：
# 1. 前端 EventSource 不支持自定义 header / POST body，所以新端点用 GET + query params
# 2. 用 LangGraph 的 astream(stream_mode="updates") 订阅节点结束事件（每完成一个节点 yield 一次）
# 3. 通过累积 chunks 拼出 final state（SearchState 是普通 TypedDict，无 reducer，直接 dict.update 即可）
# 4. 用 asyncio.timeout(240) 保持与 /search 一致的总超时
# 5. 缓存复用 /search 的 SQLite 缓存（缓存命中时不走 astream，直接 yield 一次 done 事件）
NODE_NAME_TO_STEP = {
    "query_decompose": 0,
    "search": 1,
    "expand_citations": 2,
    "rank": 3,
    "refine": 4,            # 可能循环多次（每次都映射到第 5 步）
    "synthesize": 5,
    "build_graph": 6,
    "track_cost": 7,
}


def _sse_format(data: dict) -> str:
    """格式化一个 SSE 事件（data 字段必须是 JSON 字符串）。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/search/stream")
@limiter.limit("5/minute;20/hour")
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1, max_length=2000, description="研究查询"),
    budget: float = Query(default=BUDGET_LIMIT_USD, ge=0.1, le=20.0),
    max_iter: int = Query(default=MAX_SEARCH_ITERATIONS, ge=1, le=5, alias="max_iter"),
    provider: Optional[str] = Query(default=None, max_length=64, description="LLM provider id"),
):
    """SSE 流式搜索端点：每完成一个 LangGraph 节点推一次进度事件。"""
    # VULN-001 Layer 0: 入口处净化 query (Round 2: 移到预算预留之前, 失败不消耗预算)
    try:
        safe_query = sanitize_query(q)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    # 校验 provider (同样在预算预留前, 失败不消耗预算)
    resolved_provider = _resolve_provider(provider)

    # H1 修复：原子化 check-and-reserve（避免 TOCTOU 竞态）
    # Round 2 CRITICAL-003: reserve 后 event_generator 内部 try/finally 兜底
    # 所有路径 (success/cache hit/timeout/exception/cancel/disconnect) 都归还预算
    await _check_and_reserve_budget(budget)

    initial = _make_initial_state(
        safe_query, max_iter, budget, resolved_provider
    )

    import time
    t0 = time.time()

    async def event_generator():
        # Round 2 CRITICAL-003: try/finally 全路径兜底, 防 SSE 客户端断开/异常/超时
        # 泄漏预算。finally 一定执行 (包括 GeneratorExit 路径), return_amount
        # 由各路径设置 (缓存命中/异常/超时 = budget, 成功 = diff)
        return_amount = budget  # 默认全还 (异常/超时/缓存命中/客户端断开)

        try:
            # 1) 缓存命中：直接复用 /search 的缓存结果（不发节点进度，瞬间 done）
            # H4 修复：用 async 版本
            # Round 2 审计 (CRITICAL-001): SSE 路径的 cache read 也必须传 provider
            cached = await get_cached_async(safe_query, max_iter, budget, provider=resolved_provider)
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
                    "elapsed": round(time.time() - t0, 2),
                })
                # 缓存命中: 本次未消耗 LLM, 全数归还 (return_amount 保持 = budget)
                return

            # 2) 正常路径：流式跑 LangGraph
            yield _sse_format({"event": "started", "cached": False, "max_iter": max_iter})

            accumulated: dict = dict(initial)
            step_count = 0

            try:
                # asyncio.timeout (Python 3.11+) 在整个 astream 块外层统一计时 240s
                async with asyncio.timeout(240.0):
                    async for chunk in search_graph.astream(initial, stream_mode="updates"):
                        for node_name, state_update in chunk.items():
                            if not isinstance(state_update, dict):
                                continue
                            # 累积 state（SearchState 是 plain TypedDict，无 reducer）
                            accumulated.update(state_update)
                            step_count += 1
                            mapped = NODE_NAME_TO_STEP.get(node_name)
                            yield _sse_format({
                                "event": "node_complete",
                                "node": node_name,
                                "step": mapped if mapped is not None else step_count,
                                "elapsed": round(time.time() - t0, 2),
                                "iteration": accumulated.get("iteration", 0),
                            })
                            # P0-1: 节点级预算硬停止 — 每完成一个节点立即检查
                            # 若 cost 已达/超预算, 推 budget_exceeded 事件后立即 return
                            # (走 finally 归还 budget, 不再 yield done 事件)
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
                                    # 客户端可能已断开, 静默吞掉 (finally 仍会归还预算)
                                    pass
                                # 实际已花 new_total, 归还差额避免过度预留
                                return_amount = max(0.0, budget - new_total)
                                return
            except TimeoutError:
                logger.warning("[/search/stream] timed out after 240s")
                # 超时: 把预留全数归还(几乎没产生成本)
                await _return_budget(budget)
                return_amount = 0.0  # 已显式归还, finally 不再二次归还
                # yield error 事件 (客户端可能已断开, 用 try/except 保护)
                try:
                    yield _sse_format({
                        "event": "error",
                        "code": "timeout",
                        "message": "搜索超时（>240s）。建议缩小查询范围或降低 max_iter。",
                    })
                except Exception:
                    pass
                return
            except Exception:
                logger.error("[/search/stream] error", exc_info=True)
                # 异常: 把预留全数归还(实际成本未知,保守起见全还)
                await _return_budget(budget)
                return_amount = 0.0  # 已显式归还, finally 不再二次归还
                try:
                    yield _sse_format({
                        "event": "error",
                        "code": "internal",
                        "message": "内部服务错误，请稍后重试",
                    })
                except Exception:
                    pass
                return

            # 3) 构造最终响应
            elapsed = time.time() - t0
            # 预算归还: 实际花费通常远低于 budget, 归还差额避免过度预留
            actual_cost = float(accumulated.get("total_cost_usd", 0.0))
            diff = budget - actual_cost
            if diff > 0.01:  # $0.01 阈值避免无意义小数运算
                return_amount = diff
            else:
                return_amount = 0.0
            # Round 5 M-1: 计算顶层 is_degraded 信号 (闭环 Round 4 banner)
            ranked = accumulated.get("ranked_papers", [])
            fallback_count = sum(1 for p in ranked if p.get("is_fallback", False))
            is_degraded = fallback_count > 0
            # Round 5 M-4: model_usage 白名单 — 去除 cost + provider 内部名
            # 只保留 { model: { tokens } }, 去掉 " (fallback to mock)" 后缀
            model_usage_raw = accumulated.get("model_usage") or {}
            model_usage_summary = {
                (k.split(" (")[0]): {"tokens": int((v or {}).get("tokens", 0))}
                for k, v in model_usage_raw.items()
            }
            response_obj = SearchResponse(
                report=accumulated.get("report", ""),
                ranked_papers=[PaperResult(**p) for p in accumulated.get("ranked_papers", [])[:25]],
                citation_graph=accumulated.get("citation_graph", {}),
                total_cost_usd=round(accumulated.get("total_cost_usd", 0.0), 4),
                total_tokens_used=accumulated.get("total_tokens_used", 0),
                model_usage_summary=model_usage_summary,
                iteration=accumulated.get("iteration", 0),
                status=accumulated.get("status", "done"),
                elapsed_seconds=round(elapsed, 2),
                is_degraded_response=is_degraded,
                fallback_paper_count=fallback_count,
            )

            # 4) 写缓存（预算已在入口处原子化预留，与 /search 一致）
            # H4 修复：用 async 版本
            # Round 2 审计 (CRITICAL-001): SSE 路径的 cache write 也必须传 provider
            try:
                await set_cached_async(
                    safe_query,
                    max_iter,
                    budget,
                    response_obj.model_dump(),
                    float(accumulated.get("total_cost_usd", 0.0)),
                    int(accumulated.get("total_tokens_used", 0)),
                    provider=resolved_provider,
                )
            except Exception as cache_err:
                logger.warning(f"[/search/stream] cache write failed (non-fatal): {cache_err}")

            # 5) 推 done 事件（result 用 model_dump，与 /search 响应结构一致）
            yield _sse_format({
                "event": "done",
                "result": response_obj.model_dump(),
                "elapsed": round(elapsed, 2),
            })
        finally:
            # Round 2 CRITICAL-003: 所有路径兜底 (成功/缓存/超时/异常/取消/客户端断开)
            # async generator 的 finally 在 GeneratorExit 时也执行, 配合 return_amount
            # 保证任何退出方式都归还预算。await 自身包 try/except 防 GeneratorExit 干扰
            if return_amount > 0.01:
                try:
                    await _return_budget(return_amount)
                except Exception as return_err:
                    logger.warning(
                        f"[/search/stream] budget return failed (non-fatal): {return_err}"
                    )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关闭 nginx 缓冲（部署相关，开发无需关心）
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
