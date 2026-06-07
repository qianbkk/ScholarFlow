"""Tests for M-2: synthesis_agent Grounding 验证 + 来源锚点表。

R9 审计发现 P0-A (综述幻觉无追溯): 旧 synthesize_node 把 LLM 输出直接 return,
没有任何 Grounding 验证或来源锚点, LLM 可发明 DOI / 混淆作者 / 拼凑虚构论文。

修复:
  1) _build_paper_anchors: 综述末尾追加可点击的原始来源锚点表 (paper_id + URL)
  2) _verify_citations_in_report: 提取综述中 **粗体标题**, 跟 ranked_papers 词集合对比,
     不匹配的列入 unverified 列表 → 综述末尾加 ⚠️ 警告提示用户核查

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
# Unit tests: _verify_citations_in_report
# ---------------------------------------------------------------------------

def test_verify_citations_in_report_no_unverified():
    """5 papers, all cited with **bold titles** matching ranked → empty unverified."""
    ranked = [
        {"title": "Deep Learning for Natural Language Processing"},
        {"title": "Transformers in Computer Vision"},
        {"title": "Graph Neural Networks Survey"},
        {"title": "Reinforcement Learning for Robotics"},
        {"title": "Federated Learning Privacy"},
    ]
    report = """
## 核心论文推荐
1. **Deep Learning for Natural Language Processing** [2023] — 经典工作
2. **Transformers in Computer Vision** [2023] — 重要进展
3. **Graph Neural Networks Survey** [2023] — 综述
4. **Reinforcement Learning for Robotics** [2023] — 应用
5. **Federated Learning Privacy** [2023] — 隐私
"""
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    assert unverified == [], (
        f"Expected empty unverified list, got: {unverified}"
    )


def test_verify_citations_in_report_with_hallucinated():
    """5 papers, report cites a fabricated **Made Up Paper Title** → unverified contains it."""
    ranked = [
        {"title": "Deep Learning for Natural Language Processing"},
        {"title": "Transformers in Computer Vision"},
        {"title": "Graph Neural Networks Survey"},
        {"title": "Reinforcement Learning for Robotics"},
        {"title": "Federated Learning Privacy"},
    ]
    # "Made Up Paper Title" (4 words, 19 chars) has no overlap with any ranked title.
    # "Another Fabricated Study" (3 words, 24 chars) similarly doesn't match.
    report = """
## 核心论文推荐
1. **Deep Learning for Natural Language Processing** [2023]
2. **Made Up Paper Title** [2023]
3. **Another Fabricated Study** [2023]
4. **Graph Neural Networks Survey** [2023]
"""
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    # Both hallucinated titles should be flagged
    assert "Made Up Paper Title" in unverified, (
        f"Expected 'Made Up Paper Title' in unverified, got: {unverified}"
    )
    assert "Another Fabricated Study" in unverified, (
        f"Expected 'Another Fabricated Study' in unverified, got: {unverified}"
    )
    # Real paper should NOT be flagged
    assert "Deep Learning for Natural Language Processing" not in unverified
    assert "Graph Neural Networks Survey" not in unverified


def test_verify_citations_in_report_short_bold_ignored():
    """Bold spans with length <= 10 are NOT added to unverified (avoids false positives on
    short bolded phrases like **AI** or **CNN**)."""
    ranked = [{"title": "Test paper"}]
    # 5-char bold + 4-char bold both length < 10, so they shouldn't appear in unverified
    report = "Some **AI** and **CNN** models are useful."
    _, unverified = synthesis_agent._verify_citations_in_report(report, ranked)
    # "AI" (2) and "CNN" (3) both < 10, so they're filtered out
    assert unverified == [], f"Expected empty (short bolds ignored), got: {unverified}"


def test_verify_citations_in_report_empty_inputs():
    """Empty report and empty ranked should return empty unverified, no crash."""
    _, unverified = synthesis_agent._verify_citations_in_report("", [])
    assert unverified == []

    _, unverified = synthesis_agent._verify_citations_in_report("No bold here.", [])
    assert unverified == []


# ---------------------------------------------------------------------------
# Unit tests: _build_paper_anchors
# ---------------------------------------------------------------------------

def test_build_paper_anchors_format():
    """3 papers → output contains header + 3 numbered list lines + SS IDs."""
    ranked = [
        {"title": "Paper Alpha", "paper_id": "ss-alpha-001", "url": "https://example.com/a"},
        {"title": "Paper Beta",  "paper_id": "ss-beta-002",  "url": "https://example.com/b"},
        {"title": "Paper Gamma", "paper_id": "ss-gamma-003", "url": "https://example.com/c"},
    ]
    anchors = synthesis_agent._build_paper_anchors(ranked)
    # Header check
    assert "## 📎 原始文献来源（可核查）" in anchors, (
        f"Expected anchor header, got:\n{anchors!r}"
    )
    # Numbered list lines
    assert "1. [Paper Alpha]" in anchors
    assert "2. [Paper Beta]" in anchors
    assert "3. [Paper Gamma]" in anchors
    # SS IDs in inline code
    for ss_id in ["ss-alpha-001", "ss-beta-002", "ss-gamma-003"]:
        assert f"SS ID: `{ss_id}`" in anchors, (
            f"Expected SS ID {ss_id} in anchors, got:\n{anchors!r}"
        )
    # URLs
    assert "https://example.com/a" in anchors
    assert "https://example.com/b" in anchors
    assert "https://example.com/c" in anchors


def test_build_paper_anchors_empty_ranked():
    """Empty ranked should return empty string (no crash, no spurious section)."""
    assert synthesis_agent._build_paper_anchors([]) == ""
    # Header should NOT appear when no papers
    assert "## 📎 原始文献来源" not in synthesis_agent._build_paper_anchors([])


def test_build_paper_anchors_missing_paper_id_falls_back_to_url():
    """If paper has no URL, fall back to semanticscholar.org URL using paper_id."""
    ranked = [
        {"title": "Paper A", "paper_id": "abc123"},  # no url
    ]
    anchors = synthesis_agent._build_paper_anchors(ranked)
    assert "https://semanticscholar.org/paper/abc123" in anchors
    assert "SS ID: `abc123`" in anchors


def test_build_paper_anchors_no_paper_id_unknown_fallback():
    """If paper has no paper_id and no url, fall back to 'unknown' / generic SS URL."""
    ranked = [
        {"title": "Paper X"},  # no paper_id, no url
    ]
    anchors = synthesis_agent._build_paper_anchors(ranked)
    assert "SS ID: `unknown`" in anchors
    # URL falls back to semanticscholar.org/paper/unknown
    assert "https://semanticscholar.org/paper/unknown" in anchors


# ---------------------------------------------------------------------------
# Integration: synthesize_node appends anchors + warning when needed
# ---------------------------------------------------------------------------

def test_synthesize_node_appends_anchors():
    """Run synthesize_node with mock LLM returning a clean report; result["report"]
    must contain the paper anchors section."""
    state = _make_state()  # 1 paper: title="Test paper", paper_id="test-ss-id"

    # Mock LLM returns a report that cites the actual ranked paper (no hallucination).
    # Important: "Test paper" has length 10, which fails the `len(cited) > 10` check,
    # so it WON'T be flagged as unverified. This keeps the test focused on anchors.
    fake_llm_output = (
        "## 研究概述\n本综述聚焦测试。\n\n"
        "## 核心论文推荐（Top 5）\n"
        "1. **A Different Long Title** [2024] — 相关性 7.0/10\n"
    )
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
    # Paper anchors section is appended
    assert "## 📎 原始文献来源（可核查）" in report, (
        f"Expected anchors header in report, got:\n{report[:500]!r}"
    )
    # Title of the ranked paper appears in the anchors
    assert "Test paper" in report
    # SS ID is in the anchors
    assert "SS ID: `test-ss-id`" in report


def test_synthesize_node_warns_on_hallucination():
    """If LLM cites a title not in ranked_papers, a ⚠️ warning must be appended."""
    state = _make_state()  # 1 paper: title="Test paper"

    # Mock LLM cites a hallucinated title: "Hallucinated Study Paper" (24 chars, 3 words)
    # which has no overlap with "Test paper".
    fake_llm_output = (
        "## 研究概述\n本综述测试。\n\n"
        "## 核心论文推荐（Top 5）\n"
        "1. **Hallucinated Study Paper** [2024] — 引用 0\n"
    )
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
    # Warning block must be present
    assert "⚠️" in report, f"Expected warning emoji in report, got:\n{report[:600]!r}"
    assert "未在检索结果中找到对应来源" in report
    # The hallucinated title appears in the warning
    assert "Hallucinated Study Paper" in report


def test_synthesize_node_anchors_use_short_title_length_ok():
    """When the only ranked paper has a short title like "Test paper" (10 chars),
    the synthesize_node must still produce a valid anchor with the paper's title."""
    state = _make_state()
    fake_llm_output = "## 研究概述\n测试。\n"
    fake_usage = {
        "model": "mock", "provider": "mock",
        "input_tokens": 50, "output_tokens": 50, "cost_usd": 0.0,
    }
    with patch.object(
        synthesis_agent, "call_llm",
        new=AsyncMock(return_value=(fake_llm_output, fake_usage)),
    ):
        result = asyncio.run(synthesis_agent.synthesize_node(state))

    report = result["report"]
    # The anchor header must be present
    assert "## 📎 原始文献来源（可核查）" in report
    # The ranked paper's title must appear
    assert "Test paper" in report
    # SS ID
    assert "SS ID: `test-ss-id`" in report
    # URL
    assert "https://example.com/paper" in report


def test_synthesize_node_no_anchors_when_no_ranked():
    """When ranked_papers is empty, synthesize_node returns early with a short message
    and does NOT add anchors (which would be empty anyway)."""
    state = _make_state(ranked=[])
    # Don't even patch call_llm — function should return before calling it.
    result = asyncio.run(synthesis_agent.synthesize_node(state))
    assert result["report"] == "未检索到相关论文。"
    # No anchors section in the early-return path
    assert "## 📎 原始文献来源" not in result["report"]
