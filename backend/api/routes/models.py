"""
backend.api.routes.models
==========================

Pydantic request/response models and the helpers that bridge
LangGraph SearchState dicts to API responses. Extracted from
`backend/main.py` so the new search router (and any future
client) can build/search responses without depending on the
FastAPI app module.

Surface:
  * PaperResult, SearchResponse, SearchRequest, SearchCancelRequest
  * _make_initial_state(safe_query, max_iterations, budget, provider,
                        status="decomposing") -> dict
  * _build_search_response(state_dict, elapsed, from_cache=False,
                           cached_payload=None) -> SearchResponse
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.config import BUDGET_LIMIT_USD, MAX_SEARCH_ITERATIONS
from backend.utils.export import papers_to_bibtex, papers_to_ris  # R10.5 P0
from backend.utils.observability import get_request_id


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
        # R10.5 Fix-P1-Audit-2.3: 补全 SearchState TypedDict 全部 Optional 字段.
        # 旧实现缺这俩, 节点用 state.get("prev_iter_cost_usd", 0.0) 兜底能跑但:
        #   1. LangGraph Checkpoint 反序列化时缺键报错 (R11+ checkpoint 续传前提)
        #   2. 严格 TypedDict 运行时校验失败
        #   3. 阅读代码时不确定 state 里到底有没有该字段
        # 修复: 显式补 None, 跟 TypedDict 声明对齐.
        "prev_iter_cost_usd": None,
        "top5_summary_cache": None,
    }


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="研究查询（中英文均可）")
    budget: float = Field(default=BUDGET_LIMIT_USD, ge=0.1, le=20.0, description="单次预算上限 USD")
    max_iterations: int = Field(default=MAX_SEARCH_ITERATIONS, ge=1, le=5, description="最大迭代轮次")
    provider: Optional[str] = Field(
        default=None,
        max_length=64,
        description="LLM provider id (kimi/glm/minimax/anthropic/deepseek)",
    )


class SearchCancelRequest(BaseModel):
    """用户主动取消 in-flight 搜索的请求 (Round 4 U2 配套)。"""
    request_id: Optional[str] = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9_\-]+$",
        description="请求 ID, 长度 ≤ 128 字符, 仅允许字母数字和 -_",
    )


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
    model_usage_summary: dict = Field(default_factory=dict)
    iteration: int
    status: str
    elapsed_seconds: float = 0.0
    is_degraded_response: bool = False
    fallback_paper_count: int = 0
    # R10.5 P0 (用户反馈): BibTeX / RIS 导出字符串, 前端直接拿
    # 给用户下载 (导入 Zotero / Mendeley / EndNote). 不需后端二次
    # 调用, 也避免前端重复格式化逻辑.
    bibtex: str = ""
    ris: str = ""


def _build_search_response(
    state_dict: dict,
    elapsed: float,
    from_cache: bool = False,
    cached_payload: dict | None = None,
) -> "SearchResponse":
    """抽 _build_search_response 统一 /search 和 /search/stream 的响应构造.

    之前两处各 ~30 行重复, 改一处就要同步另一处 (DUP-001+002).
    """
    if from_cache and cached_payload is not None:
        # 缓存命中: 直接用 cached payload, 但补上 is_degraded 派生
        ranked = cached_payload.get("ranked_papers", [])
        fallback_count = sum(1 for p in ranked if p.get("is_fallback", False))
        cached_payload["is_degraded_response"] = fallback_count > 0
        cached_payload["fallback_paper_count"] = fallback_count
        return SearchResponse(**cached_payload)

    # 正常路径
    ranked = state_dict.get("ranked_papers", []) or []
    fallback_count = sum(1 for p in ranked if p.get("is_fallback", False))
    is_degraded = fallback_count > 0

    def _public_model_label(key: str) -> str:
        """Map internal model/task name to public label (whitelist)."""
        base = key.split(" (")[0]
        if any(p in base for p in (
            "MiniMax", "kimi", "k2", "M2.7", "M3",
            "sonnet", "haiku", "opus",
            "deepseek", "chatgpt", "gpt-",
            "glm",
        )):
            return "language_model"
        if "score" in base or "batch" in base or "rank" in base:
            return "scoring"
        if "decompose" in base or "refine" in base:
            return "query_planning"
        return "other"

    # R10.5 Fix-P0-e2e: 必须同时复制 tokens + cost. 旧实现只复制 tokens,
    # 前端 CostDashboard 在 ${info.cost.toFixed(4)} 抛 TypeError → ErrorBoundary
    # 触发 → 真实 LLM 搜索后白屏. 修: 同时回填 cost 字段, 用 round 防精度爆炸.
    model_usage_summary = {
        _public_model_label(k): {
            "tokens": int((v or {}).get("tokens", 0)),
            "cost": round(float((v or {}).get("cost", 0.0)), 6),
        }
        for k, v in (state_dict.get("model_usage") or {}).items()
    }

    return SearchResponse(
        report=state_dict.get("report", ""),
        ranked_papers=[PaperResult(**p) for p in ranked[:25]],
        citation_graph=state_dict.get("citation_graph", {}),
        total_cost_usd=round(float(state_dict.get("total_cost_usd", 0.0)), 4),
        total_tokens_used=state_dict.get("total_tokens_used", 0),
        model_usage_summary=model_usage_summary,
        iteration=state_dict.get("iteration", 0),
        status=state_dict.get("status", "done"),
        elapsed_seconds=round(elapsed, 2),
        is_degraded_response=is_degraded,
        fallback_paper_count=fallback_count,
        # R10.5 P0: 在响应构造时同步生成 BibTeX / RIS, 前端可直接下载
        # 不用再调单独的 /export 端点. 论文列表为空时输出空串.
        bibtex=papers_to_bibtex(ranked[:25]) if ranked else "",
        ris=papers_to_ris(ranked[:25]) if ranked else "",
    )
