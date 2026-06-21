"""
backend.api.routes.search
==========================

Search endpoints — the heavy paths: /search (POST), /search/stream
(SSE), and /search/cancel. Extracted from backend/main.py during the
god-object refactor.

NOTE on mounting
----------------
This module exposes a fully functional `router = APIRouter(...)` so
`backend.main` can mount it with `app.include_router(search_router)`.
The original in-main routes are kept thin wrappers (or are removed in
follow-up refactors) to satisfy the source-level static test guards
in test_budget_try_finally.py / test_budget_node_hard_stop.py /
test_sse_disconnect_budget.py / test_request_id_propagation.py that
read `backend/main.py` source for specific markers (async def search,
_budget_return, 'budget_exceeded', get_cached_async(..., provider=),
X-Request-ID, etc.).

For now this router is the *implementation reference*; the live
endpoints are defined in `backend/main.py` and bind to the helpers
imported from this module. Once the static guards are migrated, the
include_router call replaces the inline definitions.

R10.5.24 (深度审计 P0 #3): 双轨入口风险 — 任何 PR 错误地加了一行
`app.include_router(search_router)` 都会让 FastAPI 同时挂 2 份 /search,
FastAPI 会用先注册的覆盖后者, 但限流器、_in_flight_searches 注册、
依赖注入都可能行为漂移. 已有 test_routes_not_double_mounted.py 静态
扫 main.py 源, 防止 include_router 误增.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Optional, TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.config import BUDGET_LIMIT_USD, MAX_SEARCH_ITERATIONS
import backend.config as _config
from backend.utils.budget_guard import check_budget
from backend.utils.cache import get_cached_async, set_cached_async
from backend.utils.observability import get_request_id
from backend.utils.runtime_mode import get_runtime_mode, is_runtime_mock  # R10.5.32 (F7): /agents/* 用
from backend.utils.sanitize import sanitize_query
from backend.workflow.graph import search_graph
from backend.api.services.budget import _check_and_reserve_budget, _return_budget
# R10.5.48 (P1 LLM cost 防御): 预算前置检查. 在 _check_and_reserve_budget 之前,
# 估算 8 节点流水线 cost, 明显超 user budget 时 fast-fail.
from backend.utils.token_estimator import pre_check_budget
from backend.api.services.providers import _resolve_provider
from backend.api.routes.models import (
    SearchRequest,
    SearchCancelRequest,
    SearchResponse,
    AgentPaperRequest,    # R10.5.32 (F7): /summarize + /critique
    AgentPaperResponse,
    _build_search_response,
    _make_initial_state,
)
# R10.5 Fix-P0-Audit-1.2: 从 utils.network 导入, 切断 search → main 循环依赖
from backend.utils.network import get_real_ip
from fastapi import Depends  # R10.5.30 D2: Depends 注入鉴权
# R10.5.30 (D2): router 加鉴权时, conftest.py 的 OPEN_MODE=true 必须在 backend.auth.dependencies
# R10.5.51 cleanup: 删 `import os as _os_for_openmode` (只剩 _get_current_user_search
# helper 用过, helper 已删). 普通 `import os` 也无其他用处, 整行删.
if TYPE_CHECKING:
    from backend.auth.dependencies import User  # noqa: F401 — type hint 专用

logger = logging.getLogger(__name__)


# Each route gets its own limiter instance (slowapi requires module-level binding).
# R10.5.30 (D2): 加 router-level Depends(get_current_user), 替代 main.py
# inline search() 里的 Depends 注入. 旧版 inline search() 显式
# `user: User = Depends(get_current_user)` 是 CG.txt P0 #1 修复的一部分
# (每个 /search 调用都验 X-API-Key / OPEN_MODE). 抽到 router 后必须保留
# 这层鉴权, 否则 search_router 一挂载就把全 /search 暴露无鉴权.
# 但 Depends 在 router 级别会被每个 endpoint 接收, 一些 endpoint
# (e.g. /search/stream) 可能签名不同, 这里先在 search() / cancel_search()
# 显式注入, 跟 main.py 旧 inline 行为完全一致.
from backend.auth.dependencies import get_current_user
# R10.5.51 cleanup (BACKLOG.md D 隐式条目, 跟整体清理同批): 删 _get_current_user_search helper (6 行).
# 旧实现为绕 conftest 模块级 OPEN_MODE 不刷新问题设了环境变量重读包装.
# 实际 conftest 已通过 monkeypatch.setenv + autouse fixture 在 import 前
# 设好 OPEN_MODE, get_current_user 读到的就是当前值, 不需要包装.

router = APIRouter(tags=["search"])
# FastAPI 0.115+ compatibility (跟 routes/admin.py 一致)
router.on_startup = []  # type: ignore[attr-defined]
router.on_shutdown = []  # type: ignore[attr-defined]
# R10.5 Fix-N: key_func 改 get_real_ip (XFF 优先), 避免反代后所有用户共享 5/min 限流桶.
limiter = Limiter(key_func=get_real_ip)


# ===== in-flight task table (Round 6 M2) =====
# key: request_id (string, FastAPI middleware 注入), value: asyncio.Task
# wrapping search_graph.ainvoke. main.py owns the canonical table; the
# router exposes helpers for testing/migration purposes.
_in_flight_searches: dict[str, asyncio.Task] = {}


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


def _pre_check_request(safe_query: str, budget: float, max_iter: int) -> None:
    """R10.5.51 (/simplify): /search + /search/stream 共享的预算前置检查.

    抽出来避免两处 6 行重复, 改一处忘另一处 → 风险. 包含:
    1. pre_check_budget: 估算 8 节点流水线 cost, 明显超 user budget 返 402
    2. (后续可能加) sanitize_query 二次校验, provider 解析, 等

    Args:
        safe_query: 已通过 sanitize 的用户 query (search 端已 sanitize)
        budget: 用户声明的单次预算上限 (req.budget)
        max_iter: 最大迭代数
    """
    pre_check_budget(
        prompt_size_chars=len(safe_query),
        user_budget=budget,
        max_iter=max_iter,
    )


# ===== R10.5.55: 运行时模式规范化 =====
def _normalize_runtime_mode(value: Optional[str]) -> str:
    """规范化用户传入的 runtime_mode 到 'llm' / 'local'.

    - None / '' / 'unknown' → 'llm' (默认 LLM 检索模式, R10.5.55 默认值变更)
    - 'real' / 'llm' → 'llm'
    - 'mock' / 'local' → 'local'
    - 其他 → 'llm' (兜底)
    """
    if not value:
        return "llm"
    v = value.strip().lower()
    if v in ("real", "llm"):
        return "llm"
    if v in ("mock", "local"):
        return "local"
    return "llm"


def _sse_format(data: dict, event_id: Optional[int] = None) -> str:
    """格式化一个 SSE 事件.

    R10.5.45 (P0/P1 SSE resilience): 加 event_id 参数. SSE 标准 id 字段
    让客户端 reconnect 时通过 Last-Event-ID header 告知服务端从哪续.
    当前阶段 (R10.5.45) 仅 emit id 字段作为基础设施, 不真正实现 resume
    (R11+ 接 LangGraph checkpointer 后再做断点续传).

    Args:
        data: 事件 payload, JSON-serializable.
        event_id: 事件序号. None = 不发 id 字段 (向后兼容).

    Returns:
        SSE 格式字符串, 末尾 \n\n 分隔.
    """
    payload = json.dumps(data, ensure_ascii=False)
    if event_id is None:
        return f"data: {payload}\n\n"
    return f"id: {event_id}\ndata: {payload}\n\n"


# ===== /search =====
# R10.5.12: 限流按 ENVIRONMENT 分档 (config.RATE_LIMITS_CURRENT).
# dev 30/min, test 1000/min, prod 5/min (旧值).
_search_limit = _config.RATE_LIMITS_CURRENT["search"]


@router.post("/search", response_model=SearchResponse)
# R10.5.30 (D2): 移除 @limiter.limit — slowapi 0.1.x 跟 FastAPI 0.115 + Pydantic v2
# + Depends 不兼容, 422 'loc: (query, req)' 把 SearchRequest 当 query. 限流在
# main.py app.state.limiter 兜底 (per-IP), 这里不再重复.
async def search(
    req: SearchRequest,
    request: Request,
    # R10.5.30 (D2): 加鉴权依赖, 跟 main.py 旧 inline 行为完全一致.
    # CG.txt P0 #1 修的一部分 (非 OPEN_MODE 强制校验 X-API-Key).
    user: User = Depends(get_current_user),
):
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

    # R10.5.51 (/simplify): 抽 _pre_check_request 共享 /search + /search/stream
    # 公共逻辑 (sanitize_query → pre_check_budget → _check_and_reserve_budget).
    # 之前两处 6 行重复, 改一处忘另一处 → 风险.
    _pre_check_request(safe_query, req.budget, req.max_iterations)
    await _check_and_reserve_budget(req.budget)
    budget_reserved = True  # try/finally 兜底标志

    initial = _make_initial_state(
        safe_query, req.max_iterations, req.budget, provider,
        runtime_mode=_normalize_runtime_mode(req.runtime_mode),
        paper_min=req.paper_min,
        paper_max=req.paper_max,
    )

    t0 = time.time()
    return_amount = req.budget

    try:
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
        req_id = get_request_id() or f"gen-{uuid.uuid4().hex[:8]}"
        asyncio_task = asyncio.create_task(search_graph.ainvoke(initial))
        _in_flight_searches[req_id] = asyncio_task
        try:
            # R10.5.1 V3-fix (HH.txt §1): 同步 /search 超时 480s → 60s.
            # 跟 main.py 同步. 长查询走 /search/stream (SSE).
            final = await asyncio.wait_for(asyncio_task, timeout=60.0)
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail="Sync search timeout. Use /api/v1/search/stream (SSE) for long queries.",
            )
        finally:
            _in_flight_searches.pop(req_id, None)
        elapsed = time.time() - t0
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
                # R10.5.29 (code-review): 加 runtime_mode 拼 cache key, 跟 main.py 对齐.
                # 旧版缺这个参数, /api/v1/search 会把 mock 模式结果缓存到默认 'real' 命名空间,
                # 真 API 后续请求会读到 mock 缓存 (跨污染).
                runtime_mode=get_runtime_mode(),
            )
        except Exception as cache_err:
            logger.warning(f"[/search] cache write failed (non-fatal): {cache_err}")

        return response_obj
    except asyncio.TimeoutError:
        # R10.5.1 V3-fix (HH.txt §1): 480s → 60s. 跟 main.py 对齐.
        # 详见 main.py 同位置注释. 长查询走 /api/v1/search/stream (SSE).
        logger.warning("[/search] timed out after 60s")
        raise HTTPException(
            status_code=504,
            detail="同步搜索超时（>60s）。建议改用 /api/v1/search/stream (SSE) 端点。",
        )
    except HTTPException:
        # R10.5.1 V3-fix: 内部 try 已 raise HTTPException(504), 外层不能再转 500
        raise
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
@router.post("/search/cancel")
# R10.5.30 (D2): 移除 @limiter.limit, 同 search() 注释.
async def cancel_search(
    req: SearchCancelRequest,
    request: Request,
    user: User = Depends(get_current_user),  # R10.5.30 D2
):
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


# ===== /search/stream (SSE) =====
@router.get("/search/stream")
# R10.5.30 (D2): 移除 @limiter.limit, 同 search() 注释.
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1, max_length=2000, description="研究查询"),
    budget: float = Query(default=BUDGET_LIMIT_USD, ge=0.1, le=20.0),
    max_iter: int = Query(default=MAX_SEARCH_ITERATIONS, ge=1, le=5, alias="max_iter"),
    provider: Optional[str] = Query(default=None, max_length=64, description="LLM provider id"),
    # R10.5.55: 运行时模式 query param. 'llm' / 'local' / 旧值 'real' / 'mock'.
    runtime_mode: Optional[str] = Query(
        default=None, max_length=16,
        description="运行时模式: 'llm' / 'local' (兼容旧值 'real'/'mock').",
    ),
    # R10.5.59: 论文数量范围 [min, max], 3-30. LLM 模式 strict ≥ 8 → 放宽 ≥ 7.
    paper_min: int = Query(default=5, ge=3, le=30, description="最少论文数"),
    paper_max: int = Query(default=10, ge=3, le=30, description="最多论文数"),
    # R10.5.45 (P0/P1 SSE resilience): 接收客户端 Last-Event-ID 重连 resume.
    # 当前阶段仅记日志 + 接受 header 透传 (R10.5.45 不真正续传,
    # R11+ 接 LangGraph checkpointer 后才能从 last_event_id 状态续).
    # 通过 query param 而非 header: fetch + ReadableStream 不容易设置
    # Last-Event-ID header (浏览器 fetch 不允许设置这个 forbidden header),
    # 走 query param 兼容.
    last_event_id: Optional[int] = Query(
        default=None, ge=0, le=10_000_000,
        description="R10.5.45 SSE resume: 客户端最后收到的 event id (R11+ 真续传, R10.5 仅 log)"
    ),
    user: User = Depends(get_current_user),  # R10.5.30 D2
):
    """SSE 流式搜索端点：每完成一个 LangGraph 节点推一次进度事件。"""
    try:
        safe_query = sanitize_query(q)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    resolved_provider = _resolve_provider(provider)

    # R10.5.51 (/simplify): 抽 _pre_check_request 共享 /search + /search/stream
    # 公共逻辑. 跟 /search 端一致.
    _pre_check_request(safe_query, budget, max_iter)
    await _check_and_reserve_budget(budget)

    initial = _make_initial_state(
        safe_query, max_iter, budget, resolved_provider,
        runtime_mode=_normalize_runtime_mode(runtime_mode),
        paper_min=paper_min,
        paper_max=paper_max,
    )

    t0 = time.time()

    # R10.5.45: 客户端 Last-Event-ID 重连. 当前不真续传, 仅记日志供观测.
    if last_event_id is not None:
        logger.info(
            f"[/search/stream] client resume request with last_event_id={last_event_id} "
            f"(R10.5.45 仅记录, 实际从事件 0 重跑; R11+ 接 checkpointer 才真续)"
        )

    async def event_generator():
        return_amount = budget
        # R10.5.45: 事件序号 (per-request). 每个 emit 的 SSE 事件带 id: <n>.
        # 客户端断线后用 Last-Event-ID 重连时, 服务端能识别客户端"已经看过几个".
        # 当前 R10.5.45 只 emit 不续; 续传逻辑 R11+ 接 LangGraph checkpointer.
        event_seq = 0

        def _emit(data: dict) -> str:
            """emit 一个 SSE 事件 + 自增序号. 替换原来 _sse_format 的位置."""
            nonlocal event_seq
            seq = event_seq
            event_seq += 1
            return _sse_format(data, event_id=seq)

        try:
            cached = await get_cached_async(
                safe_query, max_iter, budget, provider=resolved_provider
            )
            if cached is not None:
                cached_response, cached_cost, cached_tokens = cached
                logger.info(
                    f"[/search/stream] cache hit q='{safe_query[:40]}'"
                )
                yield _emit({"event": "started", "cached": True})
                yield _emit({
                    "event": "done",
                    "cached": True,
                    "result": cached_response,
                    "elapsed": round(time.time() - t0, 2),
                })
                return

            yield _emit({"event": "started", "cached": False, "max_iter": max_iter})

            accumulated: dict = dict(initial)
            step_count = 0
            iteration_id = 0  # Phase 2: 演化时间轴 - 记录当前迭代版本

            try:
                # R10.5 Fix 10: 240 → 480s. 跟 /search 非流式 endpoint 对齐.
                # 详见 /search 端的 TimeoutError 注释.
                async with asyncio.timeout(480.0):
                    # Phase 1: 使用 astream_events 替代 astream，捕获节点进入/退出事件
                    async for event in search_graph.astream_events(initial, version="v2"):
                        # R10.5.30 (D2): LangGraph 0.2+ astream_events 用 "event" 字段
                        # 不是 "type" (老代码搜 'type' 永远 None, 节点事件全丢).
                        # 兼容两边: 'event' 优先, 'type' fallback.
                        event_type = event.get("event") or event.get("type")

                        # R10.5.44 (P0 SSE robustness): 客户端断开检测.
                        # 旧实现: 无 is_disconnected 检查, client 断开后 astream
                        # 继续跑完整个 8 节点 (浪费 token + 时间). 每次循环开头
                        # 检查一次, FastAPI Request.is_disconnected() 是非阻塞
                        # 检测 (无网络 IO), 几乎无开销. 断开后立即 return,
                        # 走 finally 返还 budget.
                        if await request.is_disconnected():
                            logger.info(
                                f"[/search/stream] client disconnected mid-pipeline "
                                f"step={step_count} "
                                f"cost=${float(accumulated.get('total_cost_usd', 0.0)):.4f}"
                            )
                            accumulated_cost = float(
                                accumulated.get("total_cost_usd", 0.0)
                            )
                            return_amount = max(0.0, budget - accumulated_cost)
                            try:
                                yield _emit({
                                    "event": "error",
                                    "code": "client_disconnected",
                                    "message": "客户端已断开, 搜索已中止, budget 已返还",
                                })
                            except Exception:
                                pass
                            return
                        
                        # Phase 1: 态势感知 - 节点开始事件
                        if event_type == "on_chain_start" and event.get("name") in NODE_NAME_TO_STEP:
                            node_name = event.get("name")
                            mapped = NODE_NAME_TO_STEP.get(node_name)
                            # 从 event 数据中提取模型信息 (如果 agent 注入了 metadata)
                            metadata = event.get("data", {}).get("input", {})
                            model_used = metadata.get("provider") or metadata.get("model", "unknown")
                            
                            yield _emit({
                                "event": "node_started",
                                "node": node_name,
                                "step": mapped if mapped is not None else step_count,
                                "elapsed": round(time.time() - t0, 2),
                                "iteration": accumulated.get("iteration", 0),
                                "model": model_used,
                                "status": "running",
                            })
                        
                        # Phase 1: 态势感知 - 节点完成事件
                        elif event_type == "on_chain_end" and event.get("name") in NODE_NAME_TO_STEP:
                            node_name = event.get("name")
                            mapped = NODE_NAME_TO_STEP.get(node_name)

                            # 提取状态更新和成本信息
                            output_data = event.get("data", {}).get("output", {})
                            if isinstance(output_data, dict):
                                accumulated.update(output_data)

                            step_count += 1
                            new_total = float(accumulated.get("total_cost_usd", 0.0))
                            budget_limit = float(
                                accumulated.get("budget_limit_usd", float("inf"))
                            )

                            # Phase 1: 增强节点完成事件 - 包含成本和模型信息
                            yield _emit({
                                "event": "node_complete",
                                "node": node_name,
                                "step": mapped if mapped is not None else step_count,
                                "elapsed": round(time.time() - t0, 2),
                                "iteration": accumulated.get("iteration", 0),
                                "cost_usd": round(new_total, 4),
                                "tokens": accumulated.get("total_tokens_used", 0),
                            })

                            # R10.5.53 (P1 UI 反馈): 节点级思考日志推前端.
                            # query_decompose / query_refiner / rank / synthesize
                            # / critic 等 LLM 节点把"思考步骤"写到
                            # state["thinking_log"][node_name], 这里 emit node_thinking.
                            # R10.5.55: 节点级流式 — astream_events v2 不暴露 agent
                            # 内部的 _step_queue 增量 (节点未完成时 state 不会 emit),
                            # 但 astream_events 在 on_chain_end 时触发, 此时
                            # _step_queue 已完整 accumulate 在 thinking_log 中.
                            # 阶段 1: 我们改成"每节点完成时 emit 该节点所有 messages",
                            # 前端 useStore dispatchSSE 改为 append 而非覆盖.
                            # 阶段 2 (R11+): astream stream_mode="updates" 可拿到
                            # chunk-level 增量, 实现真正的逐行流式.
                            thinking_log = accumulated.get("thinking_log") or {}
                            node_thinking = thinking_log.get(node_name)
                            if node_thinking:
                                yield _emit({
                                    "event": "node_thinking",
                                    "node": node_name,
                                    "step": mapped if mapped is not None else step_count,
                                    "messages": list(node_thinking),
                                })

                            # Phase 2: 演化时间轴 - 每次迭代完成时记录图谱快照
                            if node_name == "build_graph":
                                iteration_id = accumulated.get("iteration", 0)
                                citation_graph = accumulated.get("citation_graph", {})
                                if citation_graph:
                                    yield _emit({
                                        "event": "graph_snapshot",
                                        "iteration": iteration_id,
                                        "graph": citation_graph,
                                        "node_count": len(citation_graph.get("nodes", [])),
                                        "link_count": len(citation_graph.get("links", [])),
                                    })
                            
                            # 预算检查
                            if check_budget(new_total, budget_limit):
                                accumulated["status"] = "budget_exceeded"
                                logger.warning(
                                    f"[/search/stream] P0-1 node-level budget hard stop: "
                                    f"cost=${new_total:.4f} >= limit=${budget_limit:.2f} "
                                    f"after node '{node_name}' (step={step_count})"
                                )
                                try:
                                    yield _emit({
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
                        
                        # Phase 3: Critic Agent - 评审事件 (未来扩展点)
                        elif event_type == "on_tool_start" or event_type == "on_llm_call":
                            # 预留：用于 Critic Agent 的工具调用和 LLM 调用追踪
                            pass
            except TimeoutError:
                # R10.5 Fix 10: 240 → 480s 错误消息同步
                logger.warning("[/search/stream] timed out after 480s")
                await _return_budget(budget)
                return_amount = 0.0
                try:
                    yield _emit({
                        "event": "error",
                        "code": "timeout",
                        "message": "搜索超时（>480s）。建议缩小查询范围或降低 max_iter。",
                    })
                except Exception:
                    pass
                return
            except asyncio.CancelledError:
                # R10.5.44 (P0 SSE robustness): 显式处理 CancelledError.
                # 旧实现: except Exception 漏掉 CancelledError (Python 3.8+
                # CancelledError 继承 BaseException 不是 Exception). 导致
                # client 断开时 budget 没正确返还 + astream 残跑.
                # 现在: 显式 except, 走 finally 返还 budget, 不依赖 Python
                # 内部 garbage collect.
                logger.info(
                    f"[/search/stream] cancelled (likely client disconnect) "
                    f"step={step_count} "
                    f"cost=${float(accumulated.get('total_cost_usd', 0.0)):.4f}"
                )
                accumulated_cost = float(
                    accumulated.get("total_cost_usd", 0.0)
                )
                return_amount = max(0.0, budget - accumulated_cost)
                # 通知 client (best-effort, 连接可能已断)
                try:
                    yield _emit({
                        "event": "error",
                        "code": "cancelled",
                        "message": "搜索被取消, budget 已返还",
                    })
                except Exception:
                    pass
                # 重新 raise 让上层 cleanup 知道 task 被取消
                raise
            except Exception:
                logger.error("[/search/stream] error", exc_info=True)
                await _return_budget(budget)
                return_amount = 0.0
                try:
                    yield _emit({
                        "event": "error",
                        "code": "internal",
                        "message": "内部服务错误，请稍后重试",
                    })
                except Exception:
                    pass
                return

            elapsed = time.time() - t0
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

            yield _emit({
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


# ===== R10.5.32 (F7): /agents/summarize + /agents/critique =====
# CommandPalette 11+2 真 handler 配套. R10.5.31 F5 留的 2 个 stub
# (summarize / critique) 现在接真后端. 不重写 critic_agent 逻辑, 直接
# 复用 call_llm + CRITIC_PROMPT_TEMPLATE. /summarize 用一个简版摘要 prompt.
# 这条是迈向 CD.txt §2.2 'planner/controller' 缺失 的第一步, 2 个 agent
# endpoint 后续可作为真正 multi-agent runtime 的基础 (Phase 2 升级).

_SUMMARIZE_PROMPT_TEMPLATE = """你是一位学术助手 (Summarizer Agent). 为以下论文生成 200 字以内的结构化摘要, 输出必须是 Markdown 格式:

## 背景
(1-2 句)

## 方法
(1-2 句)

## 结果
(1-2 句)

## 结论
(1 句)

## 待评审论文
标题: {title}
摘要: {abstract}
"""


@router.post("/agents/summarize", response_model=AgentPaperResponse)
async def summarize_paper(
    req: AgentPaperRequest,
    user: User = Depends(get_current_user),
) -> AgentPaperResponse:
    """CommandPalette /summarize: 给选中论文生成 200 字结构化摘要 (MD 格式)."""
    from backend.utils.llm_client import call_llm
    from backend.api.services.providers import _resolve_provider
    import time as _time

    t0 = _time.time()
    # 选 provider — _resolve_provider 只接 provider, 不接 user_id
    provider_id = _resolve_provider("minimax")
    prompt = _SUMMARIZE_PROMPT_TEMPLATE.format(
        title=req.title,
        abstract=req.abstract or "无摘要",
    )
    try:
        text, usage = await call_llm(
            prompt=prompt,
            model_override="gpt-4o-mini",
            task_type="fast",
            provider=provider_id,
            max_tokens=500,
            json_mode=False,
        )
    except Exception as exc:
        # 兜底: 摘要失败返错误信息, 前端显示 stub
        return AgentPaperResponse(
            paper_id=req.paper_id,
            agent="summarize",
            result={"summary_md": f"_摘要生成失败: {exc}_"},
            total_cost_usd=0.0,
            total_tokens_used=0,
            elapsed_seconds=round(_time.time() - t0, 2),
            runtime_mode=("local" if is_runtime_mock() else "llm"),
        )

    return AgentPaperResponse(
        paper_id=req.paper_id,
        agent="summarize",
        result={"summary_md": text.strip()},
        total_cost_usd=float((usage or {}).get("cost", 0.0)),
        total_tokens_used=int((usage or {}).get("tokens", 0)),
        elapsed_seconds=round(_time.time() - t0, 2),
        runtime_mode=("local" if is_runtime_mock() else "llm"),
    )


@router.post("/agents/critique", response_model=AgentPaperResponse)
async def critique_paper(
    req: AgentPaperRequest,
    user: User = Depends(get_current_user),
) -> AgentPaperResponse:
    """CommandPalette /critique: 复用 critic_agent 评审逻辑, 返 quality_score + recommendation."""
    from backend.agents.critic_agent import CRITIC_PROMPT_TEMPLATE
    from backend.utils.llm_client import call_llm
    from backend.api.services.providers import _resolve_provider
    import time as _time
    import json as _json

    t0 = _time.time()
    provider_id = _resolve_provider("minimax")
    prompt = CRITIC_PROMPT_TEMPLATE.format(
        title=req.title,
        abstract=req.abstract or "无摘要",
        query=req.query or "通用学术研究",
    )
    try:
        text, usage = await call_llm(
            prompt=prompt,
            model_override="gpt-4o-mini",
            task_type="fast",
            provider=provider_id,
            max_tokens=500,
            json_mode=True,
        )
    except Exception as exc:
        return AgentPaperResponse(
            paper_id=req.paper_id,
            agent="critique",
            result={"error": f"_评审失败: {exc}_"},
            total_cost_usd=0.0,
            total_tokens_used=0,
            elapsed_seconds=round(_time.time() - t0, 2),
            runtime_mode=("local" if is_runtime_mock() else "llm"),
        )

    # 解析 LLM JSON 输出, 拿 quality_score + recommendation
    try:
        # 找 JSON 块 (LLM 可能裹在 markdown 里)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            review = _json.loads(text[start:end])
        else:
            review = {"raw_response": text[:200]}
    except _json.JSONDecodeError:
        review = {"raw_response": text[:200]}

    return AgentPaperResponse(
        paper_id=req.paper_id,
        agent="critique",
        result=review,
        total_cost_usd=float((usage or {}).get("cost", 0.0)),
        total_tokens_used=int((usage or {}).get("tokens", 0)),
        elapsed_seconds=round(_time.time() - t0, 2),
        runtime_mode=("local" if is_runtime_mock() else "llm"),
    )
