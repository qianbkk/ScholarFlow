"""Tests for ranker_agent._authority_score — Fix-I/J 年份归一化 + venue bonus.

覆盖:
  1. 年均引用数分段 (新发表加成)
  2. venue bonus 加成
  3. clamp 到 10.0
  4. year=0 退化 (缺失年份)
  5. 跟 paper.citation_count=0 边界

补 8 节点单测覆盖 (X-9 报告 R10.5 缺 5 个, ranker 是最复杂的).
"""
from __future__ import annotations

import pytest

from backend.agents.ranker_agent import _authority_score


class TestAuthorityScoreNormalization:
    """Fix-J: 年均引用数分段, 防老论文系统性占优."""

    def test_recent_high_impact_paper_beats_old_dated_paper(self):
        """2024 年 100 引 (年 100) 应 >= 2010 年 500 引 (年 ~35)."""
        recent = _authority_score(citation_count=100, year=2024)
        old = _authority_score(citation_count=500, year=2010)
        assert recent >= old, (
            f"recent={recent} < old={old}: 年均归一化失败, "
            f"2010 500 引 1.5%/年 < 2024 100 引 100%/年"
        )

    def test_brand_new_paper_with_moderate_citations_gets_boost(self):
        """发表不足 2 年 + 30+ 引, 加 0.8 基础分加成."""
        # age=1, 50 引, 年均 50, 基础分应 >= 8.0 (50 → 8.0 段), 加成后 8.8
        score = _authority_score(citation_count=50, year=2025)
        baseline = _authority_score(citation_count=50, year=2020)  # age=6, 无加成
        assert score >= baseline, "新发表加成未生效"
        # 至少 8.0
        assert score >= 8.0

    def test_missing_year_falls_back_to_10_year_assumption(self):
        """year=0 → 当作 10 年前, 走兜底路径不抛异常."""
        score_no_year = _authority_score(citation_count=100, year=0)
        score_old_year = _authority_score(citation_count=100, year=2016)
        # year=0 走 max(1, current - 0) = 10, 跟 2016 接近 (current=2026)
        assert abs(score_no_year - score_old_year) < 0.5

    def test_zero_citation_returns_baseline(self):
        """0 引论文给基础分 2.0, 不应返回 0 或 None."""
        score = _authority_score(citation_count=0, year=2024)
        assert score >= 2.0

    def test_venue_bonus_clamped_to_10(self):
        """venue 加成不能突破 10.0 上限."""
        score = _authority_score(
            citation_count=100000, venue="Nature", year=2020,
        )
        assert score <= 10.0


class TestAuthorityScoreBackwardsCompat:
    """旧调用 (无 year 参数) 不报错, 走默认行为."""

    def test_no_year_uses_default_behavior(self):
        # 不传 year 走 max(1, 10) 分母, 跟 2016 接近
        score_old = _authority_score(citation_count=200, venue="")
        score_year_2016 = _authority_score(citation_count=200, venue="", year=2016)
        assert abs(score_old - score_year_2016) < 0.5
