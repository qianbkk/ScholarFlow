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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.workflow.graph import search_graph
from backend.api import semantic_scholar as _ss_mod
from backend.api import openalex as _oa_mod
from backend.utils.proxy import get_proxy  # 预热代理缓存
from backend.utils.sanitize import sanitize_query  # VULN-001
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
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
        return SearchResponse(
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
        "endpoints": ["GET /health", "POST /search"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
