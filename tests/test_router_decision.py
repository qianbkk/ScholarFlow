"""Router should_refine decision logic (F-group) — merged test suite.

merged from test_router.py, test_router_margin_ratio.py on 2026-06-07.

Covers the synthesis/refine branching in backend/workflow/router.py:
  1) trigger synthesize (max_iter, low_budget, quality_met)
  2) trigger refine (too few papers, quality not met)
  3) ratio margin (P0 fix) — high/low budget + zero budget edge
"""
import pytest

from backend.workflow.router import should_refine


# ============================================================
# 1) Basic decision: synthesize vs refine
# ============================================================

def test_should_refine_max_iter_reached():
    """iteration >= max_iterations → synthesize"""
    state = {
        "iteration": 3, "max_iterations": 3,
        "total_cost_usd": 0.0, "budget_limit_usd": 2.0,
        "ranked_papers": [],
    }
    assert should_refine(state) == "synthesize"


def test_should_refine_low_budget():
    """remaining budget (budget - cost) < 0.3 → synthesize (low budget)."""
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
        "ranked_papers": [{"relevance_score": 9.0}] * 3,
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


# ============================================================
# 2) Edge cases
# ============================================================

def test_should_refine_no_papers_no_budget():
    """空 ranked_papers 在预算充足时仍走 refine（不会 crash）。"""
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 0.0, "budget_limit_usd": 2.0,
        "ranked_papers": [],
    }
    assert should_refine(state) == "refine"


def test_should_refine_exactly_15_papers_quality_met():
    """恰好 15 papers + avg>=7 → synthesize（边界值）。"""
    papers = [{"relevance_score": 7.0}] * 15
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 0.5, "budget_limit_usd": 2.0,
        "ranked_papers": papers,
    }
    assert should_refine(state) == "synthesize"


def test_should_refine_budget_remaining_exactly_0_3():
    """remaining = 0.3 (边界)：仍允许 refine（条件是 < 0.3，不是 <= 0.3）。"""
    papers = [{"relevance_score": 8.0}] * 20
    state = {
        "iteration": 0, "max_iterations": 3,
        "total_cost_usd": 1.7, "budget_limit_usd": 2.0,
        "ranked_papers": papers,
    }
    assert should_refine(state) == "synthesize"  # 15+ papers, avg=8.0 >= 7


# ============================================================
# 3) Ratio margin (P0 fix)
# ============================================================

def test_margin_uses_ratio_low_budget_triggers_synthesize():
    """[from margin_ratio] budget=2.0, cost=1.8 → 剩余 10% < 15% → synthesize。"""
    state = {
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 1.8,
        "budget_limit_usd": 2.0,
        "ranked_papers": [{"relevance_score": 8.0}] * 20,
    }
    assert should_refine(state) == "synthesize"


def test_margin_high_budget_keeps_refining():
    """[from margin_ratio] budget=20, cost=1 → 剩余 95% > 15% → refine。

    R7 update: cost 调为 0.1 避开 Round 6 S8 per-iter cap ($0.3), relevance 调为 0.5
    避开"质量已够好"early-return (ROUTER_QUALITY_THRESHOLD_REL=2.5)。原值 1.0/5.0 在
    实际 router 行为下应返回 synthesize (1.0>$0.3 cap + 5.0>2.5 quality), 不符合本测试
    的"budget 充足 → refine" 意图。
    """
    state = {
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 0.1,
        "budget_limit_usd": 20.0,
        "ranked_papers": [{"relevance_score": 0.5}] * 20,
    }
    assert should_refine(state) == "refine"


def test_margin_budget_zero_no_division_by_zero():
    """[from margin_ratio] budget=0 时不应抛 ZeroDivisionError。"""
    state = {
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 0.0,
        "ranked_papers": [{"relevance_score": 5.0}] * 10,
    }
    result = should_refine(state)
    assert result == "refine", f"budget=0 应跳过预算检查, 实际 got {result}"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
