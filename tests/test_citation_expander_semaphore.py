"""引文扩展 Semaphore 限速 (P1) 修复测试。

旧 bug：expand_citations_node 一次并发 10 个 SS API 请求
(5 backward + 5 forward)，可能触发 100 req/5min 限流。

修复：引入 asyncio.Semaphore(4) 限制**单批** backward/forward 并发。
两个批次各自最多 4 并发，全局峰值 8（仍低于限流上限）。

测试要点：
  1) 同时 mock get_references / get_citations 模拟 100ms 慢调用
  2) N=5 seeds 时，并发峰值不超过 4
  3) Semaphore 阻塞期间其他协程可继续 yield（不卡死）
  4) 修复后整体行为（结果合并/上限）不变
"""
import asyncio
import time

import pytest

from backend.models.paper import Paper
from backend.models.state import SearchState
from backend.agents import citation_expander
from backend.agents.citation_expander import expand_citations_node


# ===== Fixtures =====

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


def _make_paper(pid, cites):
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
        source="semantic_scholar",
    )


# ===== 1) 真实 Semaphore 限速验证 =====

@pytest.mark.asyncio
async def test_semaphore_caps_concurrent_invocations(monkeypatch):
    """5 个 seed + 限速 4：单批内同时 in-flight 的 SS 调用不应超过 4。"""
    concurrent = 0
    peak = 0
    barrier = None

    async def fake_get_references(paper_id, limit=30):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        # 让调用挂着，模拟 SS 网络延迟
        await asyncio.sleep(0.05)
        concurrent -= 1
        return []

    async def fake_get_citations(paper_id, limit=20):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.05)
        concurrent -= 1
        return []

    # mock 掉 _throttled_call 里的 SS API 调用
    from backend.api import semantic_scholar
    monkeypatch.setattr(semantic_scholar, "get_references", fake_get_references)
    monkeypatch.setattr(semantic_scholar, "get_citations", fake_get_citations)

    # 5 个 seeds（>= 4 才会触发限速）
    raw = [_make_paper(f"ss_seed_{i}", cites=1000 - i) for i in range(5)]
    state = _build_state(raw)
    result = await expand_citations_node(state)

    # 验证：单批 in-flight 峰值不超过 Semaphore 限额 (4)
    assert peak <= 4, f"Semaphore 限速失败: peak concurrent = {peak} (应 <= 4)"
    # 验证：状态机仍正常推进
    assert result["status"] == "ranking"


@pytest.mark.asyncio
async def test_semaphore_releases_after_batch(monkeypatch):
    """Semaphore 必须正确释放，否则第二批 forward 调用会全部被卡住。"""
    releases = {"backward_released": False, "forward_started": False}

    async def fake_get_references(paper_id, limit=30):
        await asyncio.sleep(0.02)
        releases["backward_released"] = True
        return []

    async def fake_get_citations(paper_id, limit=20):
        # 如果 Semaphore 没释放，这里会无限等待
        try:
            await asyncio.wait_for(asyncio.shield(asyncio.sleep(0.02)), timeout=2.0)
            releases["forward_started"] = True
        except asyncio.TimeoutError:
            releases["forward_started"] = "TIMEOUT"
        return []

    from backend.api import semantic_scholar
    monkeypatch.setattr(semantic_scholar, "get_references", fake_get_references)
    monkeypatch.setattr(semantic_scholar, "get_citations", fake_get_citations)

    raw = [_make_paper(f"ss_seed_{i}", 100 - i) for i in range(5)]
    state = _build_state(raw)
    await expand_citations_node(state)

    # 第二批 forward 应能正常启动（Semaphore 已被 backward 释放）
    assert releases["backward_released"] is True
    assert releases["forward_started"] is True


# ===== 2) 限速后整体行为仍正确 =====

@pytest.mark.asyncio
async def test_results_still_merge_correctly_under_throttle(monkeypatch):
    """限速后 backward + forward 结果仍正确合并。"""
    call_count = {"backward": 0, "forward": 0}

    async def fake_get_references(paper_id, limit=30):
        call_count["backward"] += 1
        await asyncio.sleep(0.01)
        # 返回 2 篇 mock ref
        return [
            _make_paper(f"{paper_id}_ref_a", 0),
            _make_paper(f"{paper_id}_ref_b", 0),
        ]

    async def fake_get_citations(paper_id, limit=20):
        call_count["forward"] += 1
        await asyncio.sleep(0.01)
        # 返回 1 篇 mock citer
        return [_make_paper(f"{paper_id}_citer_x", 0)]

    from backend.api import semantic_scholar
    monkeypatch.setattr(semantic_scholar, "get_references", fake_get_references)
    monkeypatch.setattr(semantic_scholar, "get_citations", fake_get_citations)

    raw = [_make_paper("ss_seed_0", 100), _make_paper("ss_seed_1", 50)]
    state = _build_state(raw)
    result = await expand_citations_node(state)

    # 验证：每个 seed 都触发了 backward + forward
    assert call_count["backward"] == 2
    assert call_count["forward"] == 2
    # 验证：扩展结果包含 raw + backward refs + forward citers
    expanded_papers = [Paper.from_dict(d) for d in result["expanded_papers"]]
    raw_ids = {p.paper_id for p in raw}
    new_ids = {p.paper_id for p in expanded_papers} - raw_ids
    # 至少应包含 seed_0_ref_a, seed_0_ref_b, seed_0_citer_x, seed_1_ref_a, ...
    assert len(new_ids) > 0, "限速后扩展结果不应为空"


# ===== 3) 旧代码 (无 Semaphore) 行为对比 / 修复后行为差异 =====

def test_throttled_call_uses_module_semaphore():
    """验证 _throttled_call 确实走 _CITATION_SEMAPHORE。"""
    assert hasattr(citation_expander, "_CITATION_SEMAPHORE"), \
        "_CITATION_SEMAPHORE 未定义（限速修复缺失）"
    sem = citation_expander._CITATION_SEMAPHORE
    # Semaphore 内部 _value 字段（CPython 实现细节，但稳定）
    assert sem._value == 4, f"Semaphore 限额应为 4，实际为 {sem._value}"


@pytest.mark.asyncio
async def test_throttled_call_wrapper_exists_and_works(monkeypatch):
    """_throttled_call 必须能正确包裹一个 awaitable。"""
    # 检查 _throttled_call 存在并可调用
    assert hasattr(citation_expander, "_throttled_call")
    assert asyncio.iscoroutinefunction(citation_expander._throttled_call)

    async def fake_coro():
        return "ok"

    result = await citation_expander._throttled_call(fake_coro())
    assert result == "ok"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
