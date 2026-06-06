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
"""
import asyncio
import logging
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar
from backend.utils.text_utils import deduplicate_papers
from backend.utils.scrub import scrub_sensitive  # VULN-004

logger = logging.getLogger(__name__)

# 扩展深度参数（控制图谱大小上限，避免下游 LLM 上下文爆炸）
SEED_LIMIT = 5              # 用前 N 篇高引论文做扩展种子
BACKWARD_LIMIT = 20         # 每篇 seed 取多少 references
FORWARD_LIMIT = 10          # 每篇 seed 取多少 citers（citations 通常更稀疏）
MAX_TOTAL_PAPERS = 50       # 扩展后总论文数上限（raw 之外的新增）

# ===== SS API 限速：单批 backward/forward 并发上限 =====
# SS 免费 tier 100 req/5min；SEED_LIMIT=5 触发 5+5=10 并发。
# 限到 4 即可把单次扩展峰值从 10 降到 8（backward 与 forward 并行各 4）。
_CITATION_SEMAPHORE = asyncio.Semaphore(4)


async def _throttled_call(coro):
    """包装 SS API 调用，强制走 _CITATION_SEMAPHORE。"""
    async with _CITATION_SEMAPHORE:
        return await coro


async def expand_citations_node(state: SearchState) -> SearchState:
    """同时做 backward（references）+ forward（citations）扩展。"""

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
        return {**state, "expanded_papers": [], "status": "ranking"}

    # 选引用数最高的前 N 篇做引文扩展（只用 SS，有结构化引用数据）
    ss_papers = [p for p in raw if p.source == "semantic_scholar" and p.paper_id]

    # ===== 跨迭代去重：跳过已扩展过的 seed =====
    seen = set(state.get("expanded_paper_ids", []))
    top = [p for p in sorted(ss_papers, key=lambda p: p.citation_count, reverse=True)[:SEED_LIMIT]
           if p.paper_id not in seen]

    if not top:
        # 没有 SS 论文 或 全部已扩展过：直接把 raw 作为 expanded，继续流程
        return {
            **state,
            "expanded_papers": [p.to_dict() for p in raw],
            "expanded_paper_ids": list(seen),
            "status": "ranking",
        }

    # ===== Backward: 取每篇 seed 的 references（限速） =====
    backward_tasks = [
        _throttled_call(semantic_scholar.get_references(p.paper_id, limit=BACKWARD_LIMIT))
        for p in top
    ]
    backward_results = await asyncio.gather(*backward_tasks, return_exceptions=True)

    # ===== Forward: 取每篇 seed 的 citers（限速，犀利评论 #8）=====
    forward_tasks = [
        _throttled_call(semantic_scholar.get_citations(p.paper_id, limit=FORWARD_LIMIT))
        for p in top
    ]
    forward_results = await asyncio.gather(*forward_tasks, return_exceptions=True)

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
        f"{n_with_edges} papers have outgoing edges)"
    )

    return {
        **state,
        "expanded_papers": [p.to_dict() for p in unique],
        "expanded_paper_ids": list(seen | {p.paper_id for p in top if p.paper_id}),
        "status": "ranking",
    }
