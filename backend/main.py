"""
ScholarFlow FastAPI 入口
========================
提供 /search 和 /health 接口
"""
import asyncio
import json
import logging
import os
import sys
import time as _time
from collections import defaultdict
from contextlib import asynccontextmanager

# 让 uvicorn 直接启动时也能找到 backend 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.workflow.graph import search_graph
from backend.api import semantic_scholar as _ss_mod
from backend.api import openalex as _oa_mod
from backend.utils.proxy import get_proxy  # 预热代理缓存
from backend.utils.sanitize import sanitize_query  # VULN-001
from backend.utils.cache import get_cached, set_cached  # result cache
from backend.config import BUDGET_LIMIT_USD, MAX_SEARCH_ITERATIONS

# NEW-002 修复：logger 移至模块级
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动期预热代理缓存，关闭期释放连接池。"""
    # 启动：预热代理检测（后台线程，避免阻塞事件循环）
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_proxy)
    logger.info("[lifespan] proxy cache pre-warmed, HTTP pool ready")
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

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS],
    # 注意：CORS 规范禁止在 allow_credentials=True 时使用通配符 "*"。
    # 本项目 API 不需要携带 cookie/凭证，因此关闭 allow_credentials。
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Rate limiting + global budget (VULN-002) =====
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 全局每小时预算计数器（进程内，RESTART 归零）
# 修复：增加磁盘持久化 — 启动时从 .budget_state.json 还原，每次累加后异步落盘
GLOBAL_HOURLY_BUDGET = float(os.getenv("GLOBAL_HOURLY_BUDGET", "50.0"))
_budget_counter: dict[str, float] = defaultdict(float)
_budget_reset_ts: float = _time.time()
_BUDGET_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".budget_state.json")
_budget_lock = asyncio.Lock()


def _load_budget_state() -> None:
    """启动时从磁盘恢复预算计数（无文件则保持默认）。"""
    global _budget_reset_ts
    try:
        with open(_BUDGET_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _budget_counter["total"] = float(data.get("total", 0.0))
            ts = float(data.get("reset_ts", _time.time()))
            # 若磁盘记录的窗口已过期，则丢弃
            if _time.time() - ts > 3600:
                _budget_counter["total"] = 0.0
                _budget_reset_ts = _time.time()
            else:
                _budget_reset_ts = ts
            logger.info(
                f"[budget] loaded persisted state: total=${_budget_counter['total']:.4f}, "
                f"reset_ts={_budget_reset_ts:.0f}"
            )
    except FileNotFoundError:
        logger.info("[budget] no persisted state file, starting fresh")
    except Exception as e:
        logger.warning(f"[budget] failed to load state: {e}, starting fresh")


def _persist_budget_state() -> None:
    """落盘当前预算计数（同步写，文件小不阻塞）。"""
    try:
        with open(_BUDGET_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"total": _budget_counter["total"], "reset_ts": _budget_reset_ts},
                f,
                ensure_ascii=False,
            )
    except Exception as e:
        logger.warning(f"[budget] failed to persist state: {e}")


# 启动时尝试恢复
_load_budget_state()


async def _persist_budget_state_async() -> None:
    """异步落盘：先取锁防并发，再写文件。"""
    async with _budget_lock:
        # 用 run_in_executor 避免阻塞事件循环
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _persist_budget_state)


def _check_global_budget() -> None:
    """每小时滚动窗口：累计总开销超过 GLOBAL_HOURLY_BUDGET 时拒绝服务。"""
    global _budget_reset_ts
    now = _time.time()
    if now - _budget_reset_ts > 3600:
        _budget_counter.clear()
        _budget_reset_ts = now
        # 新窗口开始时也落盘（total 归零）
        _persist_budget_state()
    if _budget_counter["total"] > GLOBAL_HOURLY_BUDGET:
        raise HTTPException(503, detail="全局预算上限已达，请稍后重试")


# ===== Request / Response Models =====

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="研究查询（中英文均可）")
    budget: float = Field(default=BUDGET_LIMIT_USD, ge=0.1, le=20.0, description="单次预算上限 USD")
    max_iterations: int = Field(default=MAX_SEARCH_ITERATIONS, ge=1, le=5, description="最大迭代轮次")


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
    model_usage: dict
    iteration: int
    status: str
    elapsed_seconds: float = 0.0


# ===== Routes =====

@app.get("/health")
async def health():
    """健康检查。"""
    return {
        "status": "ok",
        "service": "ScholarFlow",
        "version": "1.0.0",
    }


@app.post("/search", response_model=SearchResponse)
@limiter.limit("5/minute;20/hour")
async def search(req: SearchRequest, request: Request):
    """主搜索接口：触发完整 8 节点流水线。"""
    # VULN-002: 全局每小时预算闸门
    _check_global_budget()
    # VULN-001 Layer 0: 入口处净化用户 query
    try:
        safe_query = sanitize_query(req.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")

    initial = {
        "original_query": safe_query,
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": req.max_iterations,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": req.budget,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
    }

    import time
    t0 = time.time()

    # 缓存命中：直接返回上次结果（避免重复跑付费流水线）
    cached = get_cached(safe_query, req.max_iterations, req.budget)
    if cached is not None:
        cached_response, cached_cost, cached_tokens = cached
        logger.info(
            f"[/search] cache hit q='{safe_query[:40]}' "
            f"cost=${cached_cost:.4f} tokens={cached_tokens}"
        )
        return SearchResponse(**cached_response)

    try:
        # 240s 上限：real 模式下 8 个 LLM 调用 + 双源检索 + 引文扩展通常需 100-180s,
        # 120s 在 query 复杂时会过早超时(Phase 3 验证: AlphaFold 查询实际 135s)
        final = await asyncio.wait_for(search_graph.ainvoke(initial), timeout=240.0)
        elapsed = time.time() - t0
        # VULN-002: 累加本次开销到全局预算（异步加锁落盘，避免并发写冲突）
        async with _budget_lock:
            _budget_counter["total"] += float(final.get("total_cost_usd", 0.0))
            # 提交后台任务落盘（不阻塞响应）
            asyncio.create_task(_persist_budget_state_async())

        response_obj = SearchResponse(
            report=final.get("report", ""),
            ranked_papers=[PaperResult(**p) for p in final.get("ranked_papers", [])[:20]],
            citation_graph=final.get("citation_graph", {}),
            total_cost_usd=round(final.get("total_cost_usd", 0.0), 4),
            total_tokens_used=final.get("total_tokens_used", 0),
            model_usage=final.get("model_usage", {}),
            iteration=final.get("iteration", 0),
            status=final.get("status", "done"),
            elapsed_seconds=round(elapsed, 2),
        )

        # 写入缓存（供下次同 query 复用，TTL 默认 24h）
        try:
            set_cached(
                safe_query,
                req.max_iterations,
                req.budget,
                response_obj.model_dump(),
                float(final.get("total_cost_usd", 0.0)),
                int(final.get("total_tokens_used", 0)),
            )
        except Exception as cache_err:
            logger.warning(f"[/search] cache write failed (non-fatal): {cache_err}")

        return response_obj
    except asyncio.TimeoutError:
        # 必须在 except Exception 之前（TimeoutError 是 Exception 子类，会被吞掉）
        logger.warning("[/search] timed out after 240s")
        raise HTTPException(
            status_code=504,
            detail="搜索超时（>240s）。建议缩小查询范围或降低 max_iterations。",
        )
    except Exception as e:
        # 仅服务端日志记详情，HTTP body 不暴露内部信息（VULN-002 修复）
        logger.error("[/search] error", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@app.get("/")
async def root():
    return {
        "service": "ScholarFlow",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["GET /health", "POST /search", "GET /search/stream"],
    }


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
):
    """SSE 流式搜索端点：每完成一个 LangGraph 节点推一次进度事件。"""
    _check_global_budget()
    try:
        safe_query = sanitize_query(q)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"查询无效: {e}")
    if not safe_query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")

    initial = {
        "original_query": safe_query,
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": max_iter,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": budget,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
    }

    import time
    t0 = time.time()

    async def event_generator():
        # 1) 缓存命中：直接复用 /search 的缓存结果（不发节点进度，瞬间 done）
        cached = get_cached(safe_query, max_iter, budget)
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
        except TimeoutError:
            logger.warning("[/search/stream] timed out after 240s")
            yield _sse_format({
                "event": "error",
                "code": "timeout",
                "message": "搜索超时（>240s）。建议缩小查询范围或降低 max_iter。",
            })
            return
        except Exception:
            logger.error("[/search/stream] error", exc_info=True)
            yield _sse_format({
                "event": "error",
                "code": "internal",
                "message": "内部服务错误，请稍后重试",
            })
            return

        # 3) 构造最终响应
        elapsed = time.time() - t0
        response_obj = SearchResponse(
            report=accumulated.get("report", ""),
            ranked_papers=[PaperResult(**p) for p in accumulated.get("ranked_papers", [])[:20]],
            citation_graph=accumulated.get("citation_graph", {}),
            total_cost_usd=round(accumulated.get("total_cost_usd", 0.0), 4),
            total_tokens_used=accumulated.get("total_tokens_used", 0),
            model_usage=accumulated.get("model_usage", {}),
            iteration=accumulated.get("iteration", 0),
            status=accumulated.get("status", "done"),
            elapsed_seconds=round(elapsed, 2),
        )

        # 4) 落预算 + 写缓存（与 /search 一致）
        try:
            async with _budget_lock:
                _budget_counter["total"] += float(accumulated.get("total_cost_usd", 0.0))
                asyncio.create_task(_persist_budget_state_async())
        except Exception:
            logger.warning("[/search/stream] budget update failed (non-fatal)")

        try:
            set_cached(
                safe_query,
                max_iter,
                budget,
                response_obj.model_dump(),
                float(accumulated.get("total_cost_usd", 0.0)),
                int(accumulated.get("total_tokens_used", 0)),
            )
        except Exception as cache_err:
            logger.warning(f"[/search/stream] cache write failed (non-fatal): {cache_err}")

        # 5) 推 done 事件（result 用 model_dump，与 /search 响应结构一致）
        yield _sse_format({
            "event": "done",
            "result": response_obj.model_dump(),
            "elapsed": round(elapsed, 2),
        })

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
