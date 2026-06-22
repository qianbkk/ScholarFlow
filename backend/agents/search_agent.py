"""
节点 ② — 多源并行检索
并发调用 Semantic Scholar + OpenAlex，合并去重。

Round 2 PERF-004 修复：search_node 加 Semaphore(4)，与 citation_expander 配合控制 SS 限流。
单次 refine 循环最多 5 迭代 × 5 子查询 = 25 次 SS 调用 (×2 OpenAlex = 50 总请求)，
无 Semaphore 时单次 gather 即触发 10 并发 + 多轮 429 风险。
Semaphore(4) 把单批并发峰值从 10 降到 4，对齐 citation_expander 的 Semaphore 限额。

R10.5 Fix-F (审计 QQQ §1.2): 模块级 _SEARCH_SEMAPHORE 跨请求共享, 3+ 并发用户
时所有人争 4 slot 性能灾难. 改为 search_node 内动态 asyncio.Semaphore(4),
per-request 独立, 不再被其他请求阻塞. 同改 citation_expander._CITATION_SEMAPHORE.
"""
import asyncio
import logging
import os
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar, openalex, arxiv, crossref, pubmed
from backend.utils.text_utils import deduplicate_papers, _safe_year
from backend.utils.scrub import scrub_sensitive  # VULN-004
from backend.utils.async_helpers import bounded_gather  # VULN-004
# R10.5.46 (P1): 共享 state 裁剪. search_node 入口也调, 第一次 pass 也有 cap.
from backend.agents._state_utils import prune_state
# R10.5.55: thinking step helper. 每个关键步骤 push 到 state._step_queue,
# SSE 路由流式 emit 给前端 PipelineProgress 渲染.
from backend.agents._step_helper import _step

logger = logging.getLogger(__name__)

# 单批 gather 并发上限常量 (per-call, 不再是 module singleton)
# P10 (P0-4 性能): 4 → 6. SS 免费版 100 req/5min (≈20 req/min), 4 → 6 后
# 短时 burst 触发 429 概率略增, 但 _get_with_retry 退避兜底 + 4 桶限流
# 总速率不变 (per-batch + 模块级 Semaphore 二级限流). 节省 10-20s.
_SEARCH_BATCH_LIMIT = 6

# R10.5.39 Phase 1.1: 多源检索. 默认启用 arXiv/Crossref/PubMed, 走环境变量
# SCHOLARFLOW_SOURCES 关掉. 例如 SCHOLARFLOW_SOURCES=ss,oa 关 arXiv 等.
# Google Scholar 不接 (scholarly 不稳且违反 ToS). 留个空位说明.
_DEFAULT_SOURCES = "ss,oa,arxiv,crossref,pubmed"
_SOURCES = [s.strip() for s in os.environ.get("SCHOLARFLOW_SOURCES", _DEFAULT_SOURCES).split(",") if s.strip()]


def _get_search_coros(query: str, limit: int):
    """Build the (source_name, coroutine) list based on _SOURCES."""
    out = []
    if "ss" in _SOURCES:
        out.append(("ss", semantic_scholar.search_papers(query, limit=limit)))
    if "oa" in _SOURCES:
        out.append(("oa", openalex.search_papers(query, limit=limit)))
    if "arxiv" in _SOURCES:
        out.append(("arxiv", arxiv.search_papers(query, limit=limit)))
    if "crossref" in _SOURCES:
        out.append(("crossref", crossref.search_papers(query, limit=limit)))
    if "pubmed" in _SOURCES:
        out.append(("pubmed", pubmed.search_papers(query, limit=limit)))
    return out


async def _throttled_search(coro, semaphore: asyncio.Semaphore):
    """包装 SS / OpenAlex 搜索调用, 强制走 caller 传入的 semaphore。

    Fix-F (R10.5): 删模块级 _SEARCH_SEMAPHORE, 改由 search_node 入口
    创建, 保证每个并发请求有自己独立的限流桶.
    """
    async with semaphore:
        return await coro


async def search_node(state: SearchState) -> SearchState:
    """并行调用双源 API，合并去重。"""

    # R10.5.46 (P1): 入口先裁剪 state. 第一次 pass (iter 1, 还没 refine) 也调,
    # 避免长 query 拉满 state (raw 50+ / expanded 50+ 不裁会跟着 LLM
    # context 走 + 序列化到 SSE 事件). 之前只 query_refine_node 调, 第一次
    # pass 没保护, 长 query 用户直接撞 token 失控.
    state = prune_state(state)

    # M-A 修复 (P0-2 PER_ITER 语义): search_agent 是每个 iter 的入口节点 (无论 iter 1
    # 由 query_decompose 调入, 还是 iter N 由 query_refiner→search 回环调入)。在节点
    # 第一行把当前累计成本快照为 prev_iter_cost_usd, 这是"本轮起点"; 后续 rank 结束时
    # router 用 iter_delta = total_cost_usd - prev_iter_cost_usd 检查本轮真实增量。
    prev_iter_cost = state.get("total_cost_usd", 0.0) or 0.0

    sub_queries = state.get("sub_queries") or []
    # R10.5.55: 流式 thinking log — 每个 phase emit 一条 _step() 给前端.
    _step(state, "search", f"🔍 启动多源检索 · {len(sub_queries)} sub_queries · 5 sources")
    if not sub_queries:
        return {
            **state,
            "raw_papers": [],
            "prev_iter_cost_usd": prev_iter_cost,
            "status": "expanding",
        }

    # Fix-F (R10.5): per-call semaphore, 每个 search_node 独立 4-slot 桶
    batch_semaphore = asyncio.Semaphore(_SEARCH_BATCH_LIMIT)

    # P10 (P1-2 性能): 跨 refine iter 的 sub_query → result 缓存.
    # 旧实现: refine 每次重新调 5 source, 即使 query 跟之前完全一样也不复用.
    # 新实现: cache 存到 state["_ss_cache"] dict, refine→search 回环时透传,
    # 同 (query, source) 第二次直接返缓存, 不发 HTTP 请求.
    # 命中率跟 refine 触发数强相关: 0 refine → 0% / 1 refine → 50-80% / 2+ refine → 80%+.
    # per-request 隔离: state["_ss_cache"] 是 state 的一部分, 不会跨 user 共享.
    _sq_cache: dict = state.get("_ss_cache") or {}
    state["_ss_cache"] = _sq_cache  # 显式写回, 防止 setdefault 偶发丢

    # R10.5.39 Phase 1.1: 多源检索. 每个子查询并发 5 个源 (默认全部启用).
    # SS/OA 限流 15/10 (Round 6 S2), arXiv/Crossref/PubMed 各 10 (polite 间隔).
    # Round 2 PERF-004: 通过 _throttled_search 走 Semaphore(4) 限流，避免 429
    # R10.5 Fix-Audit-Bounded-Gather: 用共享 bounded_gather 助手, 消 3x 复制粘贴.
    # R10.5.40 review: source_name was captured but unused. The lightweight fix
    # is to log it at the gather site (debug level) — full per-source error
    # attribution requires refactoring bounded_gather to accept (name, coro)
    # pairs, which is out of scope here.
    # P10 (P1-2 性能): state["_ss_cache"] 跨 iter 复用 (query, source) → result.
    # 命中直接返缓存 list (不重新 HTTP). 命中率跟 refine iter 数强相关.
    tasks_with_source: list[tuple[str, object]] = []
    for q in sub_queries:
        for source_name, coro in _get_search_coros(q, limit=10):
            cache_key = (q.lower().strip(), source_name)
            if cache_key in _sq_cache:
                # 缓存命中: 用一个立即返回的 coroutine 替代真实 HTTP 调用
                async def _cached(_key=cache_key):
                    return list(_sq_cache[_key])
                tasks_with_source.append((source_name, _cached()))
            else:
                # 未命中: 走真实 HTTP, gather 后回写 cache
                async def _uncached(_c=coro, _key=cache_key):
                    result = await _c
                    _sq_cache[_key] = result
                    return result
                tasks_with_source.append((source_name, _throttled_search(_uncached(), batch_semaphore)))
    tasks = [t for _, t in tasks_with_source]
    source_names = [n for n, _ in tasks_with_source]
    # R10.5.55: 按 source 分别 _step() 报告检索状态.
    unique_sources = sorted(set(source_names))
    for src in unique_sources:
        _step(state, "search", f"📡 检索 {src} · {source_names.count(src)} 个并行请求")

    # R10.5 Fix-Timeout: per-gather 30s 上限, 防慢响应累计 timeout.
    # P10 (P2-2 fail-fast): 旧 60s 截断 → 30s. 配合 P1-5 SS 熔断, SS 限速下
    # 1 次失败立即熔断, 30s 截断进一步减少等待. 实测节省 15-30s.
    results = await bounded_gather(
        tasks, label="search_node", timeout=30.0,
    )

    all_papers: list[Paper] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            # BUG-002 修复：去掉裸 print，改用 logger
            # R10.5.40 review fix: attribute the failure to its source by
            # position in the gather results. source_names is parallel to
            # results by construction (we built them in the same loop).
            src = source_names[i] if i < len(source_names) else "unknown"
            logger.warning(f"[search_node] {src} task exception: {type(result).__name__}: {scrub_sensitive(str(result))}")
            continue
        if isinstance(result, list):
            all_papers.extend(result)

    # 过滤无摘要论文
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique_papers = deduplicate_papers(all_papers)
    _step(state, "search", f"✅ 检索完成 · {len(unique_papers)} unique papers")

    # R10.5.55: LLM 检索模式不允许降级到 mock/fallback 数据. 过滤掉
    # is_fallback=True 的论文, 只保留真实学术 API 返回的.
    # 'local' 模式保留 fallback (用于离线演示 + API 不可用时降级).
    runtime_mode = state.get("runtime_mode") or "llm"
    if runtime_mode == "llm":
        before = len(unique_papers)
        unique_papers = [p for p in unique_papers if not getattr(p, "is_fallback", False)]
        if before != len(unique_papers):
            logger.info(
                f"[search_node] LLM mode: dropped {before - len(unique_papers)} "
                f"fallback papers, kept {len(unique_papers)} real"
            )

    # R10.5.14 (P0-B): 应用 query_decomposer 抽出的结构化约束 (year_range / venues).
    # SS/OA 的 search endpoint 都不支持精确 venue 过滤, 客户端二次过滤最稳.
    # 没传 constraints / 字段为 None 时跳过该维度, 行为跟未加约束一致.
    # R10.5.16 (code-review fix): 跨 iter 合并后也要再过滤, 否则 iter 1 没过滤
    # 的旧论文会"漏网"进 iter 2 的 unique_papers — 拆成 _apply_constraints helper,
    # 在 merge 前 + merge 后都跑一遍.
    constraints = state.get("constraints") or {}
    yr = constraints.get("year_range")
    venues = constraints.get("venues")
    norm_venues = [v.lower() for v in venues if v] if isinstance(venues, list) else []

    def _apply_constraints(papers: list[Paper]) -> list[Paper]:
        """R10.5.16: 把 year_range + venues 约束应用到 paper list, 返回过滤后.
        任一字段 None/空 跳过该维度. 调用方传入 任意 list 都能用."""
        out = papers
        if isinstance(yr, list) and len(yr) == 2:
            lo, hi = int(yr[0]), int(yr[1])
            before = len(out)
            # R10.5.17: 用 _safe_year 替代 `getattr(p, "year", 0) or 0`,
            # 区分 None (缺值) 跟 0 (合法极早/placeholder). 旧 anti-pattern
            # 会把 year=0 误判为 falsy 过滤掉.
            out = [p for p in out if lo <= _safe_year(p) <= hi]
            if before != len(out):
                logger.info(f"[search_node] year_range=[{lo},{hi}] filter: {before} -> {len(out)}")
        if norm_venues:
            # 匹配规则: 论文 venue 字段 (Semantic Scholar 'venue' / OpenAlex primary_location.display_name)
            # 大小写不敏感 + 子串包含 (e.g. 用户写 "NeurIPS", 论文 venue 可能是 "NeurIPS 2023")
            before = len(out)
            out = [
                p for p in out
                if any(v in (getattr(p, "venue", "") or "").lower() for v in norm_venues)
            ]
            if before != len(out):
                logger.info(f"[search_node] venues={venues} filter: {before} -> {len(out)}")
        return out
    # methods / datasets 不在客户端过滤 (论文字段不直接暴露), 由下游 rank / synthesize 利用

    # 第二轮及以前合并后要再过滤一次 — 见 _apply_constraints docstring
    unique_papers = _apply_constraints(unique_papers)

    # 第二轮及以后：与已有论文合并
    iteration = state.get("iteration", 0)
    if iteration > 0:
        existing_dicts = state.get("ranked_papers") or state.get("expanded_papers") or state.get("raw_papers") or []
        if existing_dicts:
            existing_papers = []
            for d in existing_dicts:
                try:
                    # BUG-004 修复：使用 from_dict 替代 Paper(**d)
                    existing_papers.append(Paper.from_dict(d))
                except Exception as e:
                    logger.warning(f"[search_node] Paper deserialize failed: {scrub_sensitive(str(e))}, keys={list(d.keys())[:5]}")
                    continue
            # R10.5.16: 合并后统一再过滤一次 — iter 1 的旧论文当年不满足当前 iter 的
            # year_range/venues 时, 要被剔除 (否则用户查 2024 时拿到 2018 的 paper).
            # 修复前只在 unique_papers 上过滤, iter 1 留下的旧论文漏网. (code-review)
            merged = deduplicate_papers(existing_papers + unique_papers)
            unique_papers = _apply_constraints(merged)

    logger.info(f"[search_node] iter={iteration} | sub_queries={len(sub_queries)} | unique={len(unique_papers)}")

    # R10.5.46 (P1 LangGraph safety net): 跟踪连续 0 结果迭代数.
    # 0 唯一论文 (deduplicate 后) → streak +1; 否则 streak = 0.
    # router.should_refine 在 streak >= 2 时强制 synthesize, 防冷门/乱码查询
    # 在 refine 循环里死磕 budget 耗尽.
    prev_streak = int(state.get("empty_result_streak") or 0)
    if len(unique_papers) == 0:
        new_streak = prev_streak + 1
    else:
        new_streak = 0

    return {
        **state,
        "raw_papers": [p.to_dict() for p in unique_papers],
        "prev_iter_cost_usd": prev_iter_cost,  # M-A P0-2: 本轮起点成本透传
        "empty_result_streak": new_streak,
        "status": "expanding",
    }
