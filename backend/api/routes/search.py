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
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.config import BUDGET_LIMIT_USD, MAX_SEARCH_ITERATIONS
from backend.utils.budget_guard import check_budget
from backend.utils.cache import get_cached_async, set_cached_async
from backend.utils.observability import get_request_id
from backend.utils.sanitize import sanitize_query
from backend.workflow.graph import search_graph
from backend.api.services.budget import _check_and_reserve_budget, _return_budget
from backend.api.services.providers import _resolve_provider
from backend.api.routes.models import (
    SearchRequest,
    SearchCancelRequest,
    SearchResponse,
    _build_search_response,
    _make_initial_state,
)
# R10.5 Fix-P0-Audit-1.2: 从 utils.network 导入, 切断 search → main 循环依赖
from backend.utils.network import get_real_ip

logger = logging.getLogger(__name__)


# Each route gets its own limiter instance (slowapi requires module-level binding).
router = APIRouter(tags=["search"])
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


def _sse_format(data: dict) -> str:
    """格式化一个 SSE 事件（data 字段必须是 JSON 字符串）。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ===== /search =====
@router.post("/search", response_model=SearchResponse)
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
            # R10.5 关键修复: 240s → 480s. 跟 main.py 跟 README 对齐.
            # 之前 Fix-10 / X-3 都没改这处 (只改了 main.py 跟 stream 端),
            # 文档承诺与实际行为再次不一致.  真实 LLM max_iter=3 67s+ 接近 240s,
            # 多次迭代会撞墙.
            final = await asyncio.wait_for(asyncio_task, timeout=480.0)
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
            )
        except Exception as cache_err:
            logger.warning(f"[/search] cache write failed (non-fatal): {cache_err}")

        return response_obj
    except asyncio.TimeoutError:
        # R10.5 Fix 10: 240 → 480s. 用户实测 8 节点全跑要 157s, max_iter=3
        # 多次迭代会逼近 240s; 480s 给 3 轮迭代 + 引文扩展留够余量.
        # (60s × 8 节点上限) 实际最坏情况 ~480s, 这是 hard ceiling.
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
@router.post("/search/cancel")
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


# ===== /search/stream (SSE) =====
@router.get("/search/stream")
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

    t0 = time.time()

    async def event_generator():
        return_amount = budget

        try:
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
                    "elapsed": round(time.time() - t0, 2),
                })
                return

            yield _sse_format({"event": "started", "cached": False, "max_iter": max_iter})

            accumulated: dict = dict(initial)
            step_count = 0

            try:
                # R10.5 Fix 10: 240 → 480s. 跟 /search 非流式 endpoint 对齐.
                # 详见 /search 端的 TimeoutError 注释.
                async with asyncio.timeout(480.0):
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
                                "elapsed": round(time.time() - t0, 2),
                                "iteration": accumulated.get("iteration", 0),
                            })
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
                # R10.5 Fix 10: 240 → 480s 错误消息同步
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
