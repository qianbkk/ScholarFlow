"""引文扩展 Semaphore 限速 (P1) 修复测试。

旧 bug：expand_citations_node 单次 fan-out 10 个 SS Graph API 请求
(5 backward + 5 forward)，极易触发免费 tier 100 req/5min 限流。

修复：引入 _CITATION_SEMAPHORE = asyncio.Semaphore(4) 限制**单批**
backward/forward 并发到 4。两个批次不互锁，全局峰值 8 (远低于限流上限)。

测试覆盖：
  1) test_citation_semaphore_value_is_4: 模块级 Semaphore 限额 = 4
  2) test_peak_concurrent_does_not_exceed_4: 5 seeds + 慢调用 → 同时 in-flight 不超 4
  3) test_throttled_call_uses_module_semaphore: _throttled_call 走 _CITATION_SEMAPHORE
"""
import asyncio
import time

import pytest

from backend.models.paper import Paper
from backend.agents import citation_expander
from backend.agents.citation_expander import (
    expand_citations_node,
    _CITATION_SEMAPHORE,
    _throttled_call,
)


# ===== Helpers =====

def _make_paper(pid: str, cites: int = 100) -> Paper:
    return Paper(
        paper_id=pid,
        title=f"Paper {pid}",
        year=2024,
        authors=["Author"],
        citation_count=cites,
        abstract=(
            f"Sufficiently long abstract for {pid} describing novel contributions "
            "to machine learning research that are useful for testing."
        ),
        venue="NeurIPS",
        source="semantic_scholar",
    )


def _build_state(raw_papers):
    return {
        "original_query": "transformer",
        "sub_queries": ["transformer"],
        "raw_papers": [p.to_dict() for p in raw_papers],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 3,
        "expanded_paper_ids": [],
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 5.0,
        "model_usage": {},
        "status": "expanding",
        "error": None,
    }


# ===== 1) Semaphore 限额是 4 =====

def test_citation_semaphore_value_is_4():
    """_CITATION_SEMAPHORE 限额应 = 4（SS free tier 100 req/5min 保护）。"""
    assert isinstance(_CITATION_SEMAPHORE, asyncio.Semaphore), (
        f"_CITATION_SEMAPHORE 应是 asyncio.Semaphore, 实际 {type(_CITATION_SEMAPHORE)}"
    )
    # asyncio.Semaphore._value 是内部计数; 初始 4
    assert _CITATION_SEMAPHORE._value == 4, (
        f"_CITATION_SEMAPHORE 限额应为 4, 实际 {_CITATION_SEMAPHORE._value}"
    )


# ===== 2) 5 seeds + 慢调用 → in-flight 不超 4 =====

@pytest.mark.asyncio
async def test_peak_concurrent_does_not_exceed_4(monkeypatch):
    """5 个 seeds + 100ms 慢调用 → 同时 in-flight 不超过 4。"""
    concurrent = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_get_references(paper_id, limit=30):
        nonlocal concurrent, peak
        async with lock:
            concurrent += 1
            peak = max(peak, concurrent)
        await asyncio.sleep(0.05)  # 慢调用,让 Semaphore 真正发挥作用
        async with lock:
            concurrent -= 1
        return []

    async def fake_get_citations(paper_id, limit=20):
        nonlocal concurrent, peak
        async with lock:
            concurrent += 1
            peak = max(peak, concurrent)
        await asyncio.sleep(0.05)
        async with lock:
            concurrent -= 1
        return []

    from backend.api import semantic_scholar
    monkeypatch.setattr(semantic_scholar, "get_references", fake_get_references)
    monkeypatch.setattr(semantic_scholar, "get_citations", fake_get_citations)

    # 5 seeds（>= 4 才会触发限速）
    raw = [_make_paper(f"ss_seed_{i}", cites=1000 - i) for i in range(5)]
    state = _build_state(raw)

    result = await expand_citations_node(state)

    # 单批 in-flight 峰值不超过 4
    assert peak <= 4, (
        f"5 seeds + 慢调用下 in-flight 峰值应 <= 4 (Semaphore 限额), 实际 {peak}"
    )
    # 验证: 应有 expanded_papers 输出 (即使空,因为 mock 返回 [])
    assert "expanded_papers" in result


# ===== 3) _throttled_call 走 _CITATION_SEMAPHORE =====

@pytest.mark.asyncio
async def test_throttled_call_caps_concurrency():
    """_throttled_call 应通过 _CITATION_SEMAPHORE 限制并发。

    Note: 不直接用模块级 _CITATION_SEMAPHORE（其绑死在模块导入时的事件循环），
    而是通过 expand_citations_node 的真实路径间接验证。
    """
    concurrent = 0
    peak = 0
    lock = asyncio.Lock()

    from backend.api import semantic_scholar

    async def fake_get_references(paper_id, limit=30):
        nonlocal concurrent, peak
        async with lock:
            concurrent += 1
            peak = max(peak, concurrent)
        await asyncio.sleep(0.05)
        async with lock:
            concurrent -= 1
        return []

    async def fake_get_citations(paper_id, limit=20):
        nonlocal concurrent, peak
        async with lock:
            concurrent += 1
            peak = max(peak, concurrent)
        await asyncio.sleep(0.05)
        async with lock:
            concurrent -= 1
        return []

    monkeypatch_p = pytest.MonkeyPatch()
    monkeypatch_p.setattr(semantic_scholar, "get_references", fake_get_references)
    monkeypatch_p.setattr(semantic_scholar, "get_citations", fake_get_citations)

    try:
        # 8 个 seeds → 16 个调用 (backward+forward)，超过 4 的限额
        raw = [_make_paper(f"ss_seed_{i}", cites=100) for i in range(8)]
        state = _build_state(raw)
        await expand_citations_node(state)
    finally:
        monkeypatch_p.undo()

    # 验证: 即使 16 个调用, 单批峰值也不超 4
    assert peak <= 4, (
        f"_throttled_call 16 并发下峰值应 <= 4, 实际 {peak}"
    )


# ===== 4) Semaphore 不阻塞 gather 完成 =====

@pytest.mark.asyncio
async def test_semaphore_does_not_break_gather(monkeypatch):
    """限速不应让 gather 卡死 — 所有任务最终完成。"""
    from backend.api import semantic_scholar

    async def fast_op(paper_id, limit=10):
        await asyncio.sleep(0.01)
        return []

    monkeypatch.setattr(semantic_scholar, "get_references", fast_op)
    monkeypatch.setattr(semantic_scholar, "get_citations", fast_op)

    raw = [_make_paper(f"ss_seed_{i}", cites=100) for i in range(3)]
    state = _build_state(raw)

    # 应正常完成, 不抛错
    result = await expand_citations_node(state)
    assert result["status"] == "ranking"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
