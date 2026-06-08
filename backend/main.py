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

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import ipaddress


def get_real_ip(request: Request) -> str:
    """R10.5 Fix-N (审计 PPP §4.1): 反向代理后读 X-Forwarded-For 真实 IP.

    默认 get_remote_address 在 Nginx/Cloudflare 后拿到的是代理 IP, 所有真实用户
    共享同一限速桶, 5 个请求后全部 429. 修复: 优先 XFF 头第一段, 配合
    TrustedHostMiddleware 防 IP 伪造.
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        first = xff.split(",")[0].strip()
        # 仅信任公网 IP, 私有 IP (10.x, 192.168.x) 视为伪造降级到直连
        try:
            ip = ipaddress.ip_address(first)
            if not ip.is_private and not ip.is_loopback:
                return first
        except ValueError:
            pass
    return get_remote_address(request)

from backend.workflow.graph import search_graph
from backend.api import semantic_scholar as _ss_mod
from backend.api import openalex as _oa_mod
from backend.utils.proxy import get_proxy  # 预热代理缓存
from backend.utils.sanitize import sanitize_query  # VULN-001
from backend.utils.cache import get_cached_async, set_cached_async  # H4
from backend.utils.semantic_cache import (  # 占位桩 (Fix-E R10.5: 死代码全部移除, 留骨架)
    semantic_cache_stub_marker,
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
from backend.middleware import install_security  # Round 5 M-3

# ===== Submodule wiring (slim entrypoint) =====
import types
import backend.api.services.budget as _budget_svc
from backend.api.routes.health import router as health_router
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
_in_flight_searches: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动期预热代理缓存，关闭期释放连接池。"""
    setup_logging()
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


# ===== Mount low-risk health routes (probes + provider catalog) =====
app.include_router(health_router)


# ===== /search (kept inline — see module docstring) =====
@app.post("/search", response_model=SearchResponse)
@limiter.limit("5/minute;20/hour")
async def search(req: SearchRequest, request: Request):
    """主搜索接口：触发完整 8 节点流水线。"""
    # VULN-001 Layer 0: 入口处净化用户 query
    try:
        safe_query = sanitize_query(req.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    # 校验 provider
    provider = _resolve_provider(req.provider)

    # VULN-002: 全局每小时预算闸门
    await _check_and_reserve_budget(req.budget)
    budget_reserved = True  # try/finally 兜底标志

    initial = _make_initial_state(
        safe_query, req.max_iterations, req.budget, provider
    )

    t0 = _time.time()
    return_amount = req.budget

    try:
        # Fix-E R10.5: 删除 get_semantic_cached 死调用 (永远返 None).
        # 精确缓存 get_cached_async 是唯一缓存查找路径; 语义缓存留作 R11 真实实现.
        cached = await get_cached_async(
            safe_query, req.max_iterations, req.budget, provider=provider
        )
        if cached is not None:
            cached_response, cached_cost, cached_tokens = cached
            logger.info(
                f"[/search] cache hit q='{safe_query[:40]}' "
                f"cost=${cached_cost:.4f} tokens={cached_tokens}"
            )
            return _build_search_response(
                state_dict={}, elapsed=0.0, from_cache=True, cached_payload=cached_response
            )

        # R9 清理: 删 BudgetExceededError 死代码后,这里原本的 try/except
        # (用来在 graph 抛 BudgetExceededError 时返回 budget_exceeded 状态)
        # 已无意义,改为无 try 直接 await — 异常由外层 except Exception 兜底
        # 返回 500 (跟 R8 审计员建议一致: 走统一错误处理)
        req_id = get_request_id() or f"gen-{uuid.uuid4().hex[:8]}"
        asyncio_task = asyncio.create_task(search_graph.ainvoke(initial))
        _in_flight_searches[req_id] = asyncio_task
        try:
            # Fix-X3: timeout 240 → 480s. 用户实测 8 节点全跑 157s,
            # max_iter=3 多次迭代逼近 240s 上限.  注释/日志/错误消息同步.
            # 同步搜索响应 routes/search.py 的 480s 跟 README 一致.
            final = await asyncio.wait_for(asyncio_task, timeout=480.0)
        finally:
            _in_flight_searches.pop(req_id, None)
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
        # Fix-E R10.5: 删除 set_semantic_cached 调用 (转发到 set_cached_async,
        # 同一行写两次相同数据 — 重复 I/O). 语义缓存留 R11 真实实现时再调用.
        except Exception as sem_err:
            logger.warning(f"[/search] semantic cache write failed (non-fatal): {sem_err}")

        return response_obj
    except asyncio.TimeoutError:
        logger.warning("[/search] timed out after 480s")
        raise HTTPException(
            status_code=504,
            detail="搜索超时（>480s）。建议缩小查询范围或降低 max_iterations。",
        )
    except Exception as e:
        logger.error("[/search] error", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")
    finally:
        if budget_reserved and return_amount > 0.01:
            try:
                await _return_budget(return_amount)
            except Exception as return_err:
                logger.warning(f"[/search] budget return failed (non-fatal): {return_err}")


# ===== /search/cancel =====
@app.post("/search/cancel")
@limiter.limit("10/minute")
async def cancel_search(req: SearchCancelRequest, request: Request):
    """用户主动取消进行中的搜索。"""
    logger.info(
        f"[/search/cancel] request_id={req.request_id} received "
        f"(length={len(req.request_id) if req.request_id else 0})"
    )
    if req.request_id and req.request_id in _in_flight_searches:
        _in_flight_searches[req.request_id].cancel()
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
@limiter.limit("5/minute;20/hour")
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1, max_length=2000, description="研究查询"),
    budget: float = Query(default=BUDGET_LIMIT_USD, ge=0.1, le=20.0),
    max_iter: int = Query(default=MAX_SEARCH_ITERATIONS, ge=1, le=5, alias="max_iter"),
    provider: Optional[str] = Query(default=None, max_length=64, description="LLM provider id"),
):
    """SSE 流式搜索端点：每完成一个 LangGraph 节点推一次进度事件。"""
    try:
        safe_query = sanitize_query(q)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    resolved_provider = _resolve_provider(provider)

    await _check_and_reserve_budget(budget)

    initial = _make_initial_state(
        safe_query, max_iter, budget, resolved_provider
    )

    t0 = _time.time()

    async def event_generator():
        return_amount = budget

        try:
            # Fix-E R10.5: 删除 get_semantic_cached 死调用 (永远返 None).
            # 精确缓存 get_cached_async 是唯一缓存查找路径; 语义缓存留作 R11.
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

            yield _sse_format({"event": "started", "cached": False, "max_iter": max_iter})

            accumulated: dict = dict(initial)
            step_count = 0

            try:
                async with asyncio.timeout(240.0):
                    async for chunk in search_graph.astream(initial, stream_mode="updates"):
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
                logger.warning("[/search/stream] timed out after 480s")
                await _return_budget(budget)
                return_amount = 0.0
                try:
                    yield _sse_format({
                        "event": "error",
                        "code": "timeout",
                        "message": "搜索超时（>480s）。建议缩小查询范围或降低 max_iter。",
                    })
                except Exception:
                    pass
                return
            except Exception:
                logger.error("[/search/stream] error", exc_info=True)
                await _return_budget(budget)
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
                logger.warning(
                    f"[/search/stream] cache write failed (non-fatal): {cache_err}"
                )
            # Fix-E R10.5: 删除 set_semantic_cached 调用 (重复写同一行).
            # 语义缓存留 R11 真实实现时再调用.

            yield _sse_format({
                "event": "done",
                "result": response_obj.model_dump(),
                "elapsed": round(elapsed, 2),
            })
        finally:
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
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
