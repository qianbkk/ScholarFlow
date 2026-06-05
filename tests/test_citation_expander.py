"""测试犀利评论 #8 修复：前向引文扩展 (forward citation expansion)。

覆盖点：
  1) `get_citations` 在 mock 模式下返回 Paper 列表且 is_expanded=True
  2) `expand_citations_node` 同时合并 backward + forward 扩展
  3) 扩展后总数不超过 MAX_TOTAL_PAPERS 上限
  4) dedupe 合并后不重复
"""
import asyncio
import pytest

from backend.api import semantic_scholar
from backend.models.paper import Paper
from backend.models.state import SearchState
from backend.agents.citation_expander import expand_citations_node


# ===== 1) get_citations 行为 =====
def test_get_citations_returns_papers_with_is_expanded(force_mock_api):
    """get_citations 应返回 Paper 列表，且每篇都带 is_expanded=True。"""
    # ss_001_transformer 在 mock 数据里被大量后续论文引用（GPT-3, BERT, Llama2 等）
    papers = asyncio.run(semantic_scholar.get_citations("ss_001_transformer", limit=20))
    assert isinstance(papers, list)
    assert len(papers) > 0, "Transformer 应至少被一些后续论文引用"
    for p in papers:
        assert isinstance(p, Paper), f"expected Paper, got {type(p).__name__}"
        assert p.is_expanded is True, f"{p.paper_id} 未标记为 expanded"
        # 引用者不应包含被查论文本身
        assert p.paper_id != "ss_001_transformer"


def test_get_citations_unknown_paper_returns_empty(force_mock_api):
    """未知 paper_id 在 mock 模式下应返回空列表（不抛错）。"""
    papers = asyncio.run(semantic_scholar.get_citations("ss_does_not_exist_9999"))
    assert papers == []


def test_get_citations_respects_limit(force_mock_api):
    """get_citations 应尊重 limit 参数。"""
    papers = asyncio.run(semantic_scholar.get_citations("ss_001_transformer", limit=3))
    assert len(papers) <= 3


# ===== 2) expand_citations_node 行为 =====
def _build_state(raw_papers: list[Paper]) -> SearchState:
    """构造一个最小可用的 SearchState 用于 expand_citations_node。"""
    return {
        "original_query": "transformer attention",
        "sub_queries": ["transformer attention"],
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


def _make_ss_paper(pid: str, title: str, year: int, cites: int) -> Paper:
    """构造一篇带 abstract 的 SS 论文。"""
    return Paper(
        paper_id=pid,
        title=title,
        year=year,
        authors=["A. Author"],
        citation_count=cites,
        abstract=(
            f"This is a sufficiently long abstract for {title}. "
            "It contains more than 80 characters of substantive text describing "
            "the paper's contributions, methods, and findings in detail."
        ),
        source="semantic_scholar",
    )


def test_expand_citations_node_combines_backward_and_forward(force_mock_api):
    """expand_citations_node 应同时做 backward + forward 扩展。"""
    raw = [
        _make_ss_paper("ss_001_transformer", "Attention Is All You Need", 2017, 95000),
        _make_ss_paper("ss_002_bert", "BERT Pretraining", 2018, 55000),
    ]
    state = _build_state(raw)
    new_state = asyncio.run(expand_citations_node(state))

    expanded = new_state.get("expanded_papers", [])
    assert len(expanded) > len(raw), "扩展后应包含 raw 之外的论文"

    # 转回 Paper 以便断言
    expanded_papers = [Paper.from_dict(d) for d in expanded]

    # 至少应包含一篇 backward ref（如 ss_001_transformer 引用的某篇 mock 论文）
    raw_ids = {p.paper_id for p in raw}
    new_paper_ids = {p.paper_id for p in expanded_papers} - raw_ids
    assert len(new_paper_ids) > 0, "扩展后应有新增论文（来自 refs 或 citers）"

    # raw 论文必须保留
    assert raw_ids.issubset({p.paper_id for p in expanded_papers}), "raw 论文被裁掉"

    # 至少有一篇带 is_expanded=True（来自 backward/forward 扩展）
    assert any(p.is_expanded for p in expanded_papers), "应有被标记为 expanded 的论文"

    # 状态机应推进到 ranking
    assert new_state.get("status") == "ranking"
    # 跨迭代去重列表应包含本次的 seeds
    assert "ss_001_transformer" in new_state.get("expanded_paper_ids", [])
    assert "ss_002_bert" in new_state.get("expanded_paper_ids", [])


def test_expand_citations_node_caps_total_papers(force_mock_api):
    """扩展后总论文数不应超过 MAX_TOTAL_PAPERS（默认 50），防止图谱爆炸。"""
    # 用 5 篇高引 SS 论文触发最大扩展
    raw = [
        _make_ss_paper("ss_001_transformer", "Attention Is All You Need", 2017, 95000),
        _make_ss_paper("ss_002_bert", "BERT Pretraining", 2018, 55000),
        _make_ss_paper("ss_003_gpt3", "GPT-3", 2020, 32000),
        _make_ss_paper("ss_004_llama2", "Llama 2", 2023, 8500),
        _make_ss_paper("ss_005_llm_survey", "LLM Survey", 2023, 4500),
    ]
    state = _build_state(raw)
    new_state = asyncio.run(expand_citations_node(state))

    expanded = new_state.get("expanded_papers", [])
    assert len(expanded) <= 50, f"总论文数 {len(expanded)} 超过上限 50"


def test_expand_citations_node_dedupes(force_mock_api):
    """同一篇论文被 backward 和 forward 双重发现时，dedup 后不应重复。"""
    raw = [_make_ss_paper("ss_001_transformer", "Attention Is All You Need", 2017, 95000)]
    state = _build_state(raw)
    new_state = asyncio.run(expand_citations_node(state))

    expanded_papers = [Paper.from_dict(d) for d in new_state.get("expanded_papers", [])]
    ids = [p.paper_id for p in expanded_papers]
    assert len(ids) == len(set(ids)), f"发现重复 paper_id: {ids}"


def test_expand_citations_node_empty_raw(force_mock_api):
    """raw_papers 为空时直接返回空结果。"""
    state = _build_state([])
    new_state = asyncio.run(expand_citations_node(state))
    assert new_state.get("expanded_papers") == []
    assert new_state.get("status") == "ranking"


if __name__ == "__main__":
    # Standalone 调试入口
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
