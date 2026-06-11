"""Tests for M-2: synthesis_agent Grounding 验证 + 警告.

R9 审计发现 P0-A (综述幻觉无追溯): 旧 synthesize_node 把 LLM 输出直接 return,
没有任何 Grounding 验证或来源锚点, LLM 可发明 DOI / 混淆作者 / 拼凑虚构论文。

R10.5.10 重构 (用户反馈 §4): 旧实现用 `**粗体**` 当"引用" → LLM 综述里所有
加粗术语 (e.g. **Transformer**、**注意力机制**) 都被误判为"未验证引用",
警告噪声巨大. 重写为检查 [N] 数字引用 + markdown 链接 paper_id 匹配:
  1) 数字引用 [1] [2, 3] [1-3] 越界 (1..len(ranked) 之外) 算 unverified
  2) SS/arXiv markdown 链接 [text](url) 中 paper_id 不在 ranked 集合 算 unverified
  3) unverified 是 dict 列表, 每条 {kind, value, reason}

本测试 mock call_llm, 让 LLM 走 mock 路径, 验证 Grounding 逻辑独立于 LLM 工作。
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.agents import synthesis_agent
from backend.models.state import SearchState


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

def _make_state(ranked: list[dict] | None = None) -> SearchState:
    """Build a minimal SearchState with configurable ranked_papers.

    Default: 1 paper titled "Test paper" with paper_id="test-ss-id".
    """
    if ranked is None:
        ranked = [
            {
                "title": "Test paper",
                "year": 2024,
                "citation_count": 10,
                "venue": "TestConf",
                "relevance_score": 8.0,
                "authority_score": 6.0,
                "consistency_score": 7.5,
                "final_score": 7.2,
                "url": "https://example.com/paper",
                "abstract": "An abstract.",
                "paper_id": "test-ss-id",
            }
        ]
    return {
        "original_query": "grounding test query",
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": ranked,
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 1,
        "expanded_paper_ids": [],
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 1.0,
        "model_usage": {},
        "status": "synthesizing",
        "error": None,
        "provider": None,
    }


# ---------------------------------------------------------------------------
# Unit tests: _verify_citations_in_report (R10.5.10 重写后)
# ---------------------------------------------------------------------------

def test_verify_index_refs_in_range_no_unverified():
    """5 papers, report cites [1] [2] [3] [4] [5] all in range → empty unverified."""
    ranked = [
        {"title": f"Paper {i}", "paper_id": f"ss-{i}"} for i in range(1, 6)
    ]
    report = """
## 核心论文推荐
1. 这是首篇 [1] 的工作
2. 第二篇 [2] 也很重要
3. 第三篇 [3] 的发现
4. 第四篇 [4] 的方法
5. 第五篇 [5] 的应用
"""
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    assert unverified == [], f"Expected empty, got: {unverified}"


def test_verify_index_refs_out_of_range_flagged():
    """引用 [6] 越界 (5 篇) → unverified 标 '6', reason='越界'."""
    ranked = [
        {"title": f"Paper {i}", "paper_id": f"ss-{i}"} for i in range(1, 6)
    ]
    report = """
## 综述
前 5 篇都相关 [1] [2] [3] [4] [5]
另提一篇 [6] (其实不存在)
还有 [99] 也提到了
"""
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    # [6] 和 [99] 越界
    out_of_range = [u for u in unverified if u['kind'] == 'index' and '越界' in u['reason']]
    values = [u['value'] for u in out_of_range]
    assert '6' in values, f"Expected '6' flagged, got: {values}"
    assert '99' in values, f"Expected '99' flagged, got: {values}"


def test_verify_index_refs_compact_list():
    """紧凑列表 [1, 2, 3] / 范围 [1-3] 都正确解析."""
    ranked = [
        {"title": f"Paper {i}", "paper_id": f"ss-{i}"} for i in range(1, 6)
    ]
    report = "研究 [1, 2, 3] 共同提出, 也参考 [4-5]."
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    assert unverified == [], f"Expected empty, got: {unverified}"


def test_verify_markdown_link_in_ranked_no_unverified():
    """markdown 链接指向 ranked 集合中的 paper_id → 不报警."""
    ranked = [
        {"title": "Real Paper", "paper_id": "abc-real-001"},
    ]
    report = "相关研究 [Real Paper](https://semanticscholar.org/paper/abc-real-001) 指出..."
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    assert unverified == [], f"Expected empty, got: {unverified}"


def test_verify_markdown_link_hallucinated_flagged():
    """markdown 链接指向不存在的 paper_id → 报警."""
    ranked = [
        {"title": "Real Paper", "paper_id": "abc-real-001"},
    ]
    report = "请参考 [Fabricated](https://arxiv.org/abs/9999.99999) 的工作."
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    # Fabricated paper_id 不在 ranked 集合
    id_unverified = [u for u in unverified if u['kind'] == 'id']
    assert len(id_unverified) >= 1, f"Expected id flagged, got: {unverified}"
    assert any('9999.99999' in u['value'] for u in id_unverified)


def test_verify_bold_terms_ignored():
    """R10.5.10 Fix: 旧实现把 **Transformer** 当未验证引用, 现不再误报.
    加粗术语 (术语标签, 不是引用) 应被忽略."""
    ranked = [{"title": "Some Paper", "paper_id": "ss-1"}]
    report = "**Transformer** 是 **注意力机制** 的一种实现, 见 [1]."
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    # 不应把 Transformer / 注意力机制 当 unverified
    assert unverified == [], (
        f"加粗术语不应被误判为未验证引用, got: {unverified}"
    )


def test_verify_empty_inputs():
    """空输入不崩."""
    _, unverified = synthesis_agent._verify_citations_in_report("", [])
    assert unverified == []

    _, unverified = synthesis_agent._verify_citations_in_report("No citations here.", [])
    assert unverified == []


# ---------------------------------------------------------------------------
# Integration: synthesize_node warning behavior
# ---------------------------------------------------------------------------

def test_synthesize_node_clean_report_no_warning():
    """LLM 报告引用全部 in-range → 不加 ⚠️ 警告."""
    state = _make_state()  # 1 paper, paper_id="test-ss-id"

    # 干净引用: [1] 在范围 (1..1)
    fake_llm_output = "本综述讨论 [1] 的工作, 用 **Transformer** 模型."
    fake_usage = {
        "model": "mock", "provider": "mock",
        "input_tokens": 100, "output_tokens": 200, "cost_usd": 0.0,
    }
    with patch.object(
        synthesis_agent, "call_llm",
        new=AsyncMock(return_value=(fake_llm_output, fake_usage)),
    ):
        result = asyncio.run(synthesis_agent.synthesize_node(state))

    report = result["report"]
    # 无警告 (引用合法 + 无 hallucinated link)
    assert "⚠️" not in report, f"Expected no warning, got:\n{report!r}"


def test_synthesize_node_warns_on_out_of_range_index():
    """LLM 报告引用越界 [99] → 加 ⚠️ 警告 (R10.5.11: HTML pre 包裹)."""
    state = _make_state()  # 1 paper, range 1..1

    # 引用 [1] (合法) + [99] (越界) + 加粗术语 (**Transformer** — R10.5.10 不再误判)
    fake_llm_output = "本综述讨论 [1] 和 [99], **Transformer** 是核心."
    fake_usage = {
        "model": "mock", "provider": "mock",
        "input_tokens": 100, "output_tokens": 200, "cost_usd": 0.0,
    }
    with patch.object(
        synthesis_agent, "call_llm",
        new=AsyncMock(return_value=(fake_llm_output, fake_usage)),
    ):
        result = asyncio.run(synthesis_agent.synthesize_node(state))

    report = result["report"]
    # 警告出现 (R10.5.11: 包在 <pre data-sf-unverified-warning> 里, 避免 marked 误判)
    assert "data-sf-unverified-warning" in report, (
        f"Expected HTML-wrapped warning, got:\n{report!r}"
    )
    assert "⚠️" in report
    assert "未在检索结果中找到对应来源" in report
    # [99] 被列出
    assert "99" in report


def test_synthesize_node_warns_on_hallucinated_link():
    """LLM 报告 hallucinate 一个 SS 链接 → 加 ⚠️ 警告."""
    state = _make_state()  # 1 paper, paper_id="test-ss-id"

    # markdown 链接指向不存在的 paper_id
    fake_llm_output = "参考 [Fake Study](https://semanticscholar.org/paper/fake-999) 的方法."
    fake_usage = {
        "model": "mock", "provider": "mock",
        "input_tokens": 100, "output_tokens": 200, "cost_usd": 0.0,
    }
    with patch.object(
        synthesis_agent, "call_llm",
        new=AsyncMock(return_value=(fake_llm_output, fake_usage)),
    ):
        result = asyncio.run(synthesis_agent.synthesize_node(state))

    report = result["report"]
    # 警告 (HTML 包裹)
    assert "data-sf-unverified-warning" in report
    assert "⚠️" in report
    # 警告里含 fake-999
    assert "fake-999" in report


def test_synthesize_node_no_anchors_when_no_ranked():
    """ranked_papers 空 → 早返回, 不加警告."""
    state = _make_state(ranked=[])
    result = asyncio.run(synthesis_agent.synthesize_node(state))
    assert result["report"] == "未检索到相关论文。"
    assert "⚠️" not in result["report"]
    # 旧 "## 📎 原始文献来源" 也确认不存在
    assert "## 📎 原始文献来源" not in result["report"]


def test_synthesize_node_warning_uses_html_pre_not_markdown_quote():
    """R10.5.11: 警告必须用 HTML pre 包裹, 不能用 markdown `> -  [N]:` 格式.
    旧 markdown 格式会让 marked 误把 [N]: 当 reference link definition,
    触发章节重新排列 (用户反馈)."""
    state = _make_state()  # 1 paper
    fake_llm_output = "讨论 [99] 时, 引用不存在的来源."  # [99] 越界
    fake_usage = {
        "model": "mock", "provider": "mock",
        "input_tokens": 100, "output_tokens": 200, "cost_usd": 0.0,
    }
    with patch.object(
        synthesis_agent, "call_llm",
        new=AsyncMock(return_value=(fake_llm_output, fake_usage)),
    ):
        result = asyncio.run(synthesis_agent.synthesize_node(state))

    report = result["report"]
    # 必须用 HTML pre, 不能用 markdown 引用语法
    assert "<pre" in report, f"Expected HTML <pre> wrapper, got:\n{report!r}"
    # 警告里不能有 markdown blockquote list 形式 (marked 会当 ref link def)
    assert "> - [99]:" not in report, (
        f"Markdown blockquote list should NOT be used (would break marked), got:\n{report!r}"
    )
