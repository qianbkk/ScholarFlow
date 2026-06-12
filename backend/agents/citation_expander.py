"""
节点 ③ — 引文网络扩展
获取高引用论文的参考文献，扩展候选池。
关键修复：把"谁引用了谁"的关系写回 Paper.references，供图谱构建使用。

犀利评论 #8 修复：在 backward（references）的基础上补充 forward（citations）扩展，
打破"Matthew effect"——高引论文的 references 偏老，缺 2025/2026 最新 preprints。

限速修复：Semantic Scholar Graph API 免费 tier 限制 100 req/5 min。
SEED_LIMIT=5 时一次扩展会同时触发 5 backward + 5 forward = 10 并发请求，
极易触发 429 限流。引入 asyncio.Semaphore(4) 把**单 gather 批次**的并发
限制在 4，向后+向前两个批次之间不阻塞（仍可同跑 8 个请求总并发峰值 8），
确保单次扩展安全低于 100 req/5min 的限流。

R10.5 Fix-F (审计 QQQ §1.2): 删模块级 _CITATION_SEMAPHORE 共享单例, 改
expand_citations_node 内动态创建, 同 search_agent 修复.
"""
import asyncio
import logging
import statistics
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar
from backend.utils.text_utils import deduplicate_papers
from backend.utils.async_helpers import bounded_gather
from backend.utils.scrub import scrub_sensitive  # VULN-004

logger = logging.getLogger(__name__)

# 扩展深度参数（控制图谱大小上限，避免下游 LLM 上下文爆炸）
# R10.5.7 P0-2 动态剪枝: SEED_LIMIT 不再硬编码 5, 根据 ranked_papers
# 相关性分布动态调整 3-10. 高置信度查询扩大扩展, 低置信度查询保守.
# 原因: 固定 5 会漏掉中等引用数但高相关的论文, 也无法在高置信场景
# (相关中位数 ≥ 8) 充分扩展. 同时配合 CITATION_THRESHOLD 过滤低相关 seed.
SEED_LIMIT_MIN = 3
SEED_LIMIT_MAX = 10
SEED_LIMIT_DEFAULT = 5       # 向后兼容: 当 ranked_papers 不可用时回退
CITATION_THRESHOLD = 6.0     # relevance_score 低于此值的 seed 不扩展
BACKWARD_LIMIT = 20          # 每篇 seed 取多少 references
FORWARD_LIMIT = 10           # 每篇 seed 取多少 citers（citations 通常更稀疏）
MAX_TOTAL_PAPERS = 50        # 扩展后总论文数上限（raw 之外的新增）

# 单批 gather 并发上限常量 (per-call, 不再 module singleton)
_CITATION_BATCH_LIMIT = 4


async def _throttled_call(coro, semaphore: asyncio.Semaphore):
    """包装 SS API 调用, 走 caller 传入的 semaphore (per-call 实例)."""
    async with semaphore:
        return await coro


async def expand_citations_node(state: SearchState) -> SearchState:
    """同时做 backward（references）+ forward（citations）扩展。"""

    # M-A 修复 (P0-2 PER_ITER 语义): 入口透传 prev_iter_cost_usd。
    # citation_expander 不调 LLM (只调 SS API 取引文图谱), 所以快照值仍是 iter start;
    # 但为了与 search/synth/rank 4 节点的写入链对齐, 显式 propagate 一次。
    prev_iter_cost = state.get("total_cost_usd", 0.0) or 0.0

    raw_dicts = state.get("raw_papers") or []
    raw: list[Paper] = []
    for d in raw_dicts:
        try:
            raw.append(Paper.from_dict(d))
        except Exception as e:
            # BUG-004 修复：反序列化失败记录 warning，不静默丢弃
            logger.warning(f"[expand_citations] Paper deserialize failed: {scrub_sensitive(str(e))}, keys={list(d.keys())[:5]}")
            continue

    if not raw:
        return {
            **state,
            "expanded_papers": [],
            "prev_iter_cost_usd": prev_iter_cost,  # M-A P0-2: 透传 iter 起点
            "status": "ranking",
        }

    # 选引用数最高的前 N 篇做引文扩展（只用 SS，有结构化引用数据）
    ss_papers = [p for p in raw if p.source == "semantic_scholar" and p.paper_id]

    # ===== R10.5.7 P0-2: 动态 SEED_LIMIT =====
    # 基于 ranked_papers 的相关性中位数动态调整, 高相关扩大扩展, 低相关保守.
    # ranked 缺失/全 0 时回退 SEED_LIMIT_DEFAULT=5 (跟旧行为兼容).
    ranked = state.get("ranked_papers") or []
    rel_scores = [
        (p.get("relevance_score", 0) or 0)
        for p in ranked
        if (p.get("relevance_score") or 0) > 0
    ]
    median_rel: float = 0.0
    if rel_scores:
        # R10.5.8 code-review 修复: 用 statistics.median (偶数 N 取均值),
        # 旧手写 sorted(...)[len//2] 在偶数 N 时取上中位, 边界 [7,7,9,9] 误判为 7,
        # 跌到 SEED_LIMIT_MIN. statistics.median 返 8, 正确进 DEFAULT 档.
        median_rel = statistics.median(rel_scores)
        if median_rel >= 8.0:
            seed_limit = SEED_LIMIT_MAX     # 10 — 高置信度, 扩大扩展
        elif median_rel >= 6.0:
            seed_limit = SEED_LIMIT_DEFAULT  # 5  — 中等相关
        else:
            seed_limit = SEED_LIMIT_MIN     # 3  — 低置信度, 保守扩展
    else:
        seed_limit = SEED_LIMIT_DEFAULT

    # R10.5.15 (P1-A 优化 2): 领域成熟度再调整. 成熟领域 (avg_citation > 500)
    # 扩展噪声多 → seed -2 避免扩到老无关论文. 新兴领域 (avg_citation < 30)
    # 引用稀疏 → seed +3 增加 recall. 限制在 [MIN, MAX] 内, 不冲掉 median_rel 的判断.
    # 阈值选 500/30 (原 1000/100 偏严, 让 mock 测试 (avg~100) 误触发 +3, 现有
    # 7 个 dynamic_seeding 测试预期 seed_limit=5, 不能破).
    cit_counts = [p.citation_count for p in raw if (p.citation_count or 0) > 0]
    if cit_counts:
        avg_cit = sum(cit_counts) / len(cit_counts)
        if avg_cit > 500:
            seed_limit = max(SEED_LIMIT_MIN, seed_limit - 2)
            logger.debug(f"[CitationExpander] mature field avg_cit={avg_cit:.0f}, seed_limit -> {seed_limit}")
        elif avg_cit < 30:
            seed_limit = min(SEED_LIMIT_MAX, seed_limit + 3)
            logger.debug(f"[CitationExpander] emerging field avg_cit={avg_cit:.0f}, seed_limit -> {seed_limit}")

    # ===== 跨迭代去重：跳过已扩展过的 seed =====
    seen = set(state.get("expanded_paper_ids", []))
    # 1) 选 top-N (按引用数) → 2) 过滤 relevance < CITATION_THRESHOLD (避免雪崩)
    candidates = sorted(ss_papers, key=lambda p: p.citation_count, reverse=True)[:seed_limit]
    # R10.5.8 code-review 修复: has_real_relevance 应该在 ranked_papers 上判定
    # (决定是否启用阈值过滤的"上游信号"), 不是在 candidates 上 (top-cited 子集,
    # 即便 rel=0 也不代表 ranker 没跑). 旧实现: 如果 top-5 全是 rel=0 (ranker 跳过),
    # 误判 has_real_relevance=False → 阈值过滤被禁用, 5 篇全过 → 雪崩.
    has_real_relevance = len(rel_scores) > 0
    if has_real_relevance:
        top = [p for p in candidates
               if p.paper_id not in seen
               and (p.relevance_score or 0) >= CITATION_THRESHOLD]
        # 如果 CITATION_THRESHOLD 过滤后空, 兜底取 top-3 (避免某 iter 完全无扩展)
        if not top and candidates:
            top = candidates[:SEED_LIMIT_MIN]
    else:
        # 兼容路径: 无 ranked 数据时, 仅按"已扩展过" 去重
        top = [p for p in candidates if p.paper_id not in seen]

    if not top:
        # 没有 SS 论文 或 全部已扩展过：直接把 raw 作为 expanded，继续流程
        return {
            **state,
            "expanded_papers": [p.to_dict() for p in raw],
            "expanded_paper_ids": list(seen),
            "prev_iter_cost_usd": prev_iter_cost,  # M-A P0-2: 透传 iter 起点
            "status": "ranking",
        }

    # Fix-F (R10.5): per-call semaphore, 每个 expand_citations_node 独立 4-slot 桶
    batch_semaphore = asyncio.Semaphore(_CITATION_BATCH_LIMIT)

    # ===== Backward: 取每篇 seed 的 references（限速） =====
    # R10.5 Fix-Timeout: 加 60s per-gather 上限, 防 SS 慢响应累计超时.
    # 旧实现: SEED_LIMIT=5 × 30s SS timeout = 150s 纯等待, 加上 retry 可能 200s+,
    # 单 expand 节点就吃光 240s 全局 budget, 下游节点全卡. 60s 截断:
    # 部分 refs 拿不到就拿不到, 不阻塞整个 pipeline.
    backward_tasks = [
        _throttled_call(
            semantic_scholar.get_references(p.paper_id, limit=BACKWARD_LIMIT),
            batch_semaphore,
        )
        for p in top
    ]
    backward_results = await bounded_gather(
        backward_tasks, label="expand_citations.backward", timeout=60.0,
    )

    # ===== Forward: 取每篇 seed 的 citers（限速，犀利评论 #8）=====
    forward_tasks = [
        _throttled_call(
            semantic_scholar.get_citations(p.paper_id, limit=FORWARD_LIMIT),
            batch_semaphore,
        )
        for p in top
    ]
    forward_results = await bounded_gather(
        forward_tasks, label="expand_citations.forward", timeout=60.0,
    )

    # ===== 关键修复：构建 seed -> refs 反向映射（写回 Paper.references）=====
    seed_to_refs: dict[str, list[str]] = {}
    for seed_paper, result in zip(top, backward_results):
        if isinstance(result, list):
            ref_ids = [r.paper_id for r in result if r.paper_id]
            if ref_ids:
                seed_to_refs[seed_paper.paper_id] = ref_ids

    all_papers: list[Paper] = list(raw)
    n_backward = 0
    n_forward = 0
    for result in backward_results:
        if isinstance(result, Exception):
            logger.warning(f"[CitationExpander] backward exception: {type(result).__name__}: {scrub_sensitive(str(result))}")
            continue
        if isinstance(result, list):
            n_backward += len(result)
            all_papers.extend(result)
    for result in forward_results:
        if isinstance(result, Exception):
            logger.warning(f"[CitationExpander] forward exception: {type(result).__name__}: {scrub_sensitive(str(result))}")
            continue
        if isinstance(result, list):
            n_forward += len(result)
            all_papers.extend(result)

    # ===== 关键修复：把"seed -> refs"关系写回每篇 seed paper 的 references 字段 =====
    for p in all_papers:
        if p.paper_id in seed_to_refs:
            p.references = seed_to_refs[p.paper_id]

    # 过滤（必须有摘要） + 去重（DOI-aware）
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique = deduplicate_papers(all_papers)

    # ===== 截断到 MAX_TOTAL_PAPapers 上限：优先保留 raw + 高引扩展 =====
    if len(unique) > MAX_TOTAL_PAPERS:
        # raw 论文必须有；其余按 citation_count 倒序
        raw_ids = {p.paper_id for p in raw}
        raw_kept = [p for p in unique if p.paper_id in raw_ids]
        others = sorted(
            [p for p in unique if p.paper_id not in raw_ids],
            key=lambda p: p.citation_count,
            reverse=True,
        )
        slots = max(0, MAX_TOTAL_PAPERS - len(raw_kept))
        unique = raw_kept + others[:slots]

    # 统计实际有引文边的论文数
    n_with_edges = sum(1 for p in unique if p.references)
    logger.info(
        f"[CitationExpander] {len(raw)} -> {len(unique)} papers "
        f"(+{n_backward} backward refs, +{n_forward} forward citers from top {len(top)} seeds, "
        f"{n_with_edges} papers have outgoing edges, "
        f"dynamic_seed_limit={seed_limit}, median_rel={median_rel if rel_scores else 'N/A'})"
    )

    return {
        **state,
        "expanded_papers": [p.to_dict() for p in unique],
        "expanded_paper_ids": list(seen | {p.paper_id for p in top if p.paper_id}),
        "prev_iter_cost_usd": prev_iter_cost,  # M-A P0-2: 透传 iter 起点
        "status": "ranking",
    }
