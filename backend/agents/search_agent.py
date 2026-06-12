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
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar, openalex
from backend.utils.text_utils import deduplicate_papers
from backend.utils.scrub import scrub_sensitive  # VULN-004
from backend.utils.async_helpers import bounded_gather  # VULN-004

logger = logging.getLogger(__name__)

# 单批 gather 并发上限常量 (per-call, 不再是 module singleton)
_SEARCH_BATCH_LIMIT = 4


async def _throttled_search(coro, semaphore: asyncio.Semaphore):
    """包装 SS / OpenAlex 搜索调用, 强制走 caller 传入的 semaphore。

    Fix-F (R10.5): 删模块级 _SEARCH_SEMAPHORE, 改由 search_node 入口
    创建, 保证每个并发请求有自己独立的限流桶.
    """
    async with semaphore:
        return await coro


async def search_node(state: SearchState) -> SearchState:
    """并行调用双源 API，合并去重。"""

    # M-A 修复 (P0-2 PER_ITER 语义): search_agent 是每个 iter 的入口节点 (无论 iter 1
    # 由 query_decompose 调入, 还是 iter N 由 query_refiner→search 回环调入)。在节点
    # 第一行把当前累计成本快照为 prev_iter_cost_usd, 这是"本轮起点"; 后续 rank 结束时
    # router 用 iter_delta = total_cost_usd - prev_iter_cost_usd 检查本轮真实增量。
    prev_iter_cost = state.get("total_cost_usd", 0.0) or 0.0

    sub_queries = state.get("sub_queries") or []
    if not sub_queries:
        return {
            **state,
            "raw_papers": [],
            "prev_iter_cost_usd": prev_iter_cost,
            "status": "expanding",
        }

    # Fix-F (R10.5): per-call semaphore, 每个 search_node 独立 4-slot 桶
    batch_semaphore = asyncio.Semaphore(_SEARCH_BATCH_LIMIT)

    # 并发搜索：每个子查询同时查两个数据库
    # Round 2 PERF-004: 通过 _throttled_search 走 Semaphore(4) 限流，避免 429
    # Round 6 S2: search_agent limit 30/20 → 15/10, 250→125 papers, 节省 50% SS/OA API 配额
    # (单次 max_iter=3 不再占满 5min 配额)
    tasks = []
    for q in sub_queries:
        tasks.append(_throttled_search(semantic_scholar.search_papers(q, limit=15), batch_semaphore))
        tasks.append(_throttled_search(openalex.search_papers(q, limit=10), batch_semaphore))

    # R10.5 Fix-Timeout: per-gather 60s 上限, 防 SS/OA 慢响应累计 timeout.
    # 60s 截断: 部分 sub_queries 拿不到结果就用空 list, 不阻塞 pipeline.
    # R10.5 Fix-Audit-Bounded-Gather: 用共享 bounded_gather 助手, 消 3x 复制粘贴.
    results = await bounded_gather(
        tasks, label="search_node", timeout=60.0,
    )

    all_papers: list[Paper] = []
    for result in results:
        if isinstance(result, Exception):
            # BUG-002 修复：去掉裸 print，改用 logger
            logger.warning(f"[search_node] task exception: {type(result).__name__}: {scrub_sensitive(str(result))}")
            continue
        if isinstance(result, list):
            all_papers.extend(result)

    # 过滤无摘要论文
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique_papers = deduplicate_papers(all_papers)

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
            out = [
                p for p in out
                if (getattr(p, "year", 0) or 0) >= lo and (getattr(p, "year", 0) or 0) <= hi
            ]
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

    return {
        **state,
        "raw_papers": [p.to_dict() for p in unique_papers],
        "prev_iter_cost_usd": prev_iter_cost,  # M-A P0-2: 本轮起点成本透传
        "status": "expanding",
    }
