"""
ScholarFlow FastAPI 入口
========================
提供 /search 和 /health 接口
"""
import asyncio
import os
import sys

# 让 uvicorn 直接启动时也能找到 backend 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.workflow.graph import search_graph
from backend.config import BUDGET_LIMIT_USD, MAX_SEARCH_ITERATIONS


app = FastAPI(
    title="ScholarFlow API",
    version="1.0.0",
    description="科研文献智能搜索系统 — 多 Agent 学术情报 API",
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
async def search(req: SearchRequest):
    """主搜索接口：触发完整 8 节点流水线。"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="查询内容不能为空")

    initial = {
        "original_query": req.query.strip(),
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
        # 120s 上限：避免 Real 模式下某个 API 卡死导致前端无限转圈
        final = await asyncio.wait_for(search_graph.ainvoke(initial), timeout=120.0)
        elapsed = time.time() - t0
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
    except Exception as e:
        print(f"[API] /search error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"搜索超时（>{120}s）。建议缩小查询范围或降低 max_iterations。",
        )


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
