"""H3 修复测试：ranker batch 在单批失败时不应崩溃。

旧实现：asyncio.gather(...) 不带 return_exceptions=True，单批失败（LLM 429 / JSON
parse error / 网络异常）会传播并崩溃整个 ranker 节点，导致整条流水线 500。

新实现：gather 用 return_exceptions=True，失败的批次用兜底分数（5.0/6.0，与
_score_papers_combined_batch 内部兜底一致）填平，其他批次正常返回。

测试要点：
  1) Mock _score_papers_combined_batch 在第 2 批（论文 p10-p19）抛 RuntimeError
  2) rank_node 应正常返回，不抛异常
  3) 30 篇论文中前 25 篇全在 ranked_papers 中（ranker 上限已统一为 25，FIX: P0 暗物质）
  4) 失败批次中前 5 名（p10-p14）有兜底分数，p15-p19 被 [:25] 截断
  5) 成功的 20 篇论文（p0-p9 + p20-p29）保留 LLM 返回的真实分数
"""
import asyncio
import pytest

from backend.agents import ranker_agent
from backend.models.paper import Paper
from backend.models.state import SearchState


# ===== Helpers =====

def _make_papers(n: int) -> list[Paper]:
    """构造 n 篇 citation_count=10 的论文（>= 3 过滤线）。"""
    papers = []
    for i in range(n):
        papers.append(Paper(
            paper_id=f"p{i:02d}",
            title=f"Paper {i}",
            year=2020,
            citation_count=10,  # pass citation >= 3 filter
        ))
    return papers


def _build_state(papers: list[Paper]) -> SearchState:
    return {
        "original_query": "test query",
        "sub_queries": ["test query"],
        "raw_papers": [p.to_dict() for p in papers],
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
        "status": "ranking",
        "error": None,
    }


# ===== H3 核心测试 =====

def test_rank_node_handles_batch_exception_gracefully(monkeypatch):
    """第 2 批（p10-p19）抛 RuntimeError 时，rank_node 不崩溃，其他批次正常。"""
    papers = _make_papers(30)  # 3 batches of 10
    state = _build_state(papers)

    REAL_RELEVANCE = 7.5
    REAL_CONSISTENCY = 8.5

    async def mock_score(batch, query, provider=None):
        # 用 paper_id 识别批次（gather 是并发的，call_count 不可靠）
        ids = [p.paper_id for p in batch]
        if "p10" in ids:  # batch 2（p10-p19）抛异常
            raise RuntimeError("simulated LLM 429")
        # 正常批次返回固定分数（便于断言）
        rels = [REAL_RELEVANCE] * len(batch)
        cons = [REAL_CONSISTENCY] * len(batch)
        usage = {"cost_usd": 0.001, "input_tokens": 10, "output_tokens": 5}
        return rels, cons, usage

    monkeypatch.setattr(ranker_agent, "_score_papers_combined_batch", mock_score)

    # 不应抛异常
    new_state = asyncio.run(ranker_agent.rank_node(state))

    # 30 篇论文中前 25 篇进入 ranked_papers（ranker 上限已统一为 25）
    # 排序细节：成功批次 20 篇 final_score=6.95, 失败批次 10 篇 final_score=5.2。
    # 稳定排序后：所有 20 篇 6.95 论文 (p00-p09 + p20-p29) 在前,然后是 5.2 论文 (p10-p19)。
    # [:25] 切走前 25 = 全部 20 篇高分 + 失败批次的 p10-p14 (前 5)。
    # 失败批次的 p15-p19 被截断，不在 ranked_papers 中。
    ranked_dicts = new_state.get("ranked_papers", [])
    assert len(ranked_dicts) == 25, f"expected 25 papers, got {len(ranked_dicts)}"

    # 按 paper_id 索引
    by_id = {p["paper_id"]: p for p in ranked_dicts}

    # 失败批次中前 5 名（p10-p14）应有兜底分数（在 ranked_papers 内）
    for i in range(10, 15):
        pid = f"p{i:02d}"
        assert pid in by_id, f"missing failed-batch top-5 paper {pid}"
        assert by_id[pid]["relevance_score"] == 5.0, (
            f"{pid} relevance should be 5.0 (fallback), got {by_id[pid]['relevance_score']}"
        )
        assert by_id[pid]["consistency_score"] == 6.0, (
            f"{pid} consistency should be 6.0 (fallback), got {by_id[pid]['consistency_score']}"
        )

    # 失败批次中后 5 名（p15-p19）应被截断不在 ranked_papers 中
    for i in range(15, 20):
        pid = f"p{i:02d}"
        assert pid not in by_id, (
            f"{pid} should be truncated by [:25] cap, but found in ranked_papers"
        )

    # 成功批次（p00-p09 + p20-p29 共 20 篇）应有 LLM 真实分数
    for i in list(range(0, 10)) + list(range(20, 30)):
        pid = f"p{i:02d}"
        assert pid in by_id, f"missing ok-batch paper {pid}"
        assert by_id[pid]["relevance_score"] == REAL_RELEVANCE, (
            f"{pid} relevance should be {REAL_RELEVANCE}, got {by_id[pid]['relevance_score']}"
        )
        assert by_id[pid]["consistency_score"] == REAL_CONSISTENCY, (
            f"{pid} consistency should be {REAL_CONSISTENCY}, got {by_id[pid]['consistency_score']}"
        )

    # 状态机应推进到 checking_refine
    assert new_state.get("status") == "checking_refine"


def test_rank_node_handles_all_batches_failing(monkeypatch):
    """所有批次都失败时，rank_node 仍不崩溃，全部用兜底分数。"""
    papers = _make_papers(20)  # 2 batches of 10
    state = _build_state(papers)

    async def mock_score(batch, query, provider=None):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(ranker_agent, "_score_papers_combined_batch", mock_score)

    new_state = asyncio.run(ranker_agent.rank_node(state))

    ranked = new_state.get("ranked_papers", [])
    assert len(ranked) == 20
    for p in ranked:
        assert p["relevance_score"] == 5.0
        assert p["consistency_score"] == 6.0


def test_rank_node_handles_single_paper_batch(monkeypatch):
    """边界：不足 1 批时（≤ 10 篇），仍走同样的兜底逻辑。"""
    papers = _make_papers(5)
    state = _build_state(papers)

    async def mock_score(batch, query, provider=None):
        raise ValueError("bad JSON")

    monkeypatch.setattr(ranker_agent, "_score_papers_combined_batch", mock_score)

    new_state = asyncio.run(ranker_agent.rank_node(state))

    ranked = new_state.get("ranked_papers", [])
    assert len(ranked) == 5
    for p in ranked:
        assert p["relevance_score"] == 5.0
        assert p["consistency_score"] == 6.0


def test_rank_node_no_exception_when_all_batches_succeed(monkeypatch):
    """全部成功时不应触发兜底；rank_node 行为与旧实现一致。"""
    papers = _make_papers(15)  # 2 batches: 10 + 5
    state = _build_state(papers)

    REAL_RELEVANCE = 8.0
    REAL_CONSISTENCY = 7.0

    async def mock_score(batch, query, provider=None):
        rels = [REAL_RELEVANCE] * len(batch)
        cons = [REAL_CONSISTENCY] * len(batch)
        usage = {"cost_usd": 0.001, "input_tokens": 10, "output_tokens": 5}
        return rels, cons, usage

    monkeypatch.setattr(ranker_agent, "_score_papers_combined_batch", mock_score)

    new_state = asyncio.run(ranker_agent.rank_node(state))

    ranked = new_state.get("ranked_papers", [])
    assert len(ranked) == 15
    for p in ranked:
        assert p["relevance_score"] == REAL_RELEVANCE
        assert p["consistency_score"] == REAL_CONSISTENCY


if __name__ == "__main__":
    # Standalone 调试入口
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
