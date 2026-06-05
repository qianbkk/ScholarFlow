"""测试 backend/workflow/router.py 的 should_refine 决策逻辑。

涵盖 4 种触发 synthesize 的条件 + 2 种触发 refine 的条件。
"""
import pytest
from backend.workflow.router import should_refine


# ===== 触发 synthesize =====

def test_should_refine_max_iter_reached():
    """iteration >= max_iterations → synthesize"""
    state = {
        "iteration": 3, "max_iterations": 3,
        "total_cost_usd": 0.0, "budget_limit_usd": 2.0,
        "ranked_papers": [],
    }
    assert should_refine(state) == "synthesize"


def test_should_refine_low_budget():
    """remaining budget (budget - cost) < 0.3 → synthesize (low budget).
    cost=1.8, budget=2.0 → remaining=0.2 < 0.3
    """
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 1.8, "budget_limit_usd": 2.0,
        "ranked_papers": [{"relevance_score": 8.0}] * 20,
    }
    assert should_refine(state) == "synthesize"


def test_should_refine_too_few_papers():
    """ranked_papers < 5 → refine"""
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 0.1, "budget_limit_usd": 2.0,
        "ranked_papers": [{"relevance_score": 9.0}] * 3,  # only 3 papers
    }
    assert should_refine(state) == "refine"


def test_should_refine_quality_met():
    """avg_relevance(top5) >= 7 AND >= 15 papers → synthesize"""
    papers = [{"relevance_score": 8.5}] * 20
    state = {
        "iteration": 1, "max_iterations": 3,
        "total_cost_usd": 0.5, "budget_limit_usd": 2.0,
        "ranked_papers": papers,
    }
    assert should_refine(state) == "synthesize"


def test_should_refine_quality_not_met():
    """avg_relevance(top5) < 7 → refine"""
    papers = [{"relevance_score": 5.0}] * 20
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 0.1, "budget_limit_usd": 2.0,
        "ranked_papers": papers,
    }
    assert should_refine(state) == "refine"


# ===== 边界条件 =====

def test_should_refine_no_papers_no_budget():
    """空 ranked_papers 在预算充足时仍走 refine（不会 crash）"""
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 0.0, "budget_limit_usd": 2.0,
        "ranked_papers": [],
    }
    assert should_refine(state) == "refine"


def test_should_refine_exactly_15_papers_quality_met():
    """恰好 15 papers + avg>=7 → synthesize（边界值）"""
    papers = [{"relevance_score": 7.0}] * 15
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 0.5, "budget_limit_usd": 2.0,
        "ranked_papers": papers,
    }
    assert should_refine(state) == "synthesize"


def test_should_refine_budget_remaining_exactly_0_3():
    """remaining = 0.3 (边界)：仍允许 refine（条件是 < 0.3，不是 <= 0.3）"""
    # cost=1.7, budget=2.0 → remaining=0.3, papers=20 with avg 8
    papers = [{"relevance_score": 8.0}] * 20
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 1.7, "budget_limit_usd": 2.0,
        "ranked_papers": papers,
    }
    assert should_refine(state) == "synthesize"  # 15+ papers, avg=8.0 >= 7
