"""router.py 比例 margin (P0) 修复测试。

旧 bug：router 用绝对值 margin（$0.3）：
  - budget=0.5 时 $0.3 margin = 60% 预算（保守过头，提前停止）
  - budget=20 时 $0.3 margin = 1.5% 预算（激进过头，不停止）

新实现：预算边际改为比例（默认 15%）。剩余预算 / budget < 0.15 时停止。
即: 用了 85% 就停 (1 - 0.15)。

测试覆盖：
  1) test_margin_uses_ratio: budget=2.0, cost=1.8 → 剩余 10% < 15% → synthesize
  2) test_margin_high_budget: budget=20, cost=1 → 剩余 95% > 15% → refine
  3) test_margin_budget_zero_safe: budget=0 → 不抛 ZeroDivisionError，正常 synthesize
"""
import pytest

from backend.workflow.router import should_refine


# ===== 1) 比例 margin 核心行为 =====

def test_margin_uses_ratio_low_budget_triggers_synthesize():
    """budget=2.0, cost=1.8 → 剩余 10% < 15% → synthesize（按比例停）。"""
    state = {
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 1.8,
        "budget_limit_usd": 2.0,
        "ranked_papers": [{"relevance_score": 8.0}] * 20,
    }
    assert should_refine(state) == "synthesize", (
        f"cost=1.8/budget=2.0 剩余 10% < 15% 应触发 synthesize, "
        f"实际 got {should_refine(state)}"
    )


# ===== 2) 高预算不轻易停止 =====

def test_margin_high_budget_keeps_refining():
    """budget=20, cost=1 → 剩余 95% > 15% → refine（不停止）。

    旧绝对值 margin=0.3: 20-1=19 >> 0.3 → 不停。结论碰巧一致，但语义不一样。
    新比例 margin=0.15: 19/20=95% >> 15% → 不停。验证"高预算不保守"。
    """
    state = {
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 1.0,
        "budget_limit_usd": 20.0,
        "ranked_papers": [{"relevance_score": 5.0}] * 20,  # 低质量,需要 refine
    }
    assert should_refine(state) == "refine", (
        f"高预算/低质量应继续 refine, 实际 got {should_refine(state)}"
    )


# ===== 3) budget=0 边界安全 =====

def test_margin_budget_zero_no_division_by_zero():
    """budget=0 时不应抛 ZeroDivisionError。

    比例计算 (budget - cost) / budget 在 budget=0 时会 ZeroDivisionError。
    修复：router 在 budget<=0 时跳过预算检查（视为无预算约束），
    后续 ranked_papers 数量 < 5 → refine。
    """
    state = {
        "iteration": 0,
        "max_iterations": 3,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 0.0,
        "ranked_papers": [{"relevance_score": 5.0}] * 10,  # 有 10 篇
    }
    # 不应抛错;有 10 篇 + 质量低 → refine
    result = should_refine(state)
    assert result == "refine", f"budget=0 应跳过预算检查, 实际 got {result}"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
