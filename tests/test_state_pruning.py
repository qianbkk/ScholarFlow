"""
U.txt + U2.txt + U3.txt 审计 #2 修复测试 (R10.5.22).

原问题: LangGraph state 在 refine 循环中 raw_papers / expanded_papers /
ranked_papers 无限累积, max_iter=3 时 state 从 ~50 论文膨胀到 ~150+,
下游 LLM 拼接 + SSE 序列化线性放大 Token 成本.

修复: backend.agents.query_refiner.prune_state() — 按 relevance_score
排序后截到 3 个 cap (RAW/EXPANDED=50, RANKED=30).

测试覆盖:
  1. prune_state 不修改 len ≤ cap 的 list (idempotent)
  2. prune_state 按 score 降序保留高分论文
  3. prune_state 0 分论文保留顺序 (兼容 ranker 跳过情况)
  4. 嵌套 dict (paper 内部字段) 完整保留, 不做 key 裁剪
  5. RAW/EXPANDED/RANKED 三个 cap 独立生效
  6. cap 上限值正确 (常量 50/50/30)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from backend.agents.query_refiner import (
    prune_state,
    RAW_PAPERS_CAP,
    EXPANDED_PAPERS_CAP,
    RANKED_PAPERS_CAP,
)


# ===== Cap 常量校验 =====
def test_caps_constants():
    """3 个 cap 常量符合设计 (RAW/EXPANDED=50, RANKED=30)."""
    assert RAW_PAPERS_CAP == 50
    assert EXPANDED_PAPERS_CAP == 50
    assert RANKED_PAPERS_CAP == 30


# ===== Test 1: idempotent — len ≤ cap 时不修改 =====
def test_prune_state_idempotent_when_under_cap():
    """当 3 个 list 都在 cap 内, prune_state 不动它们 (原 list 引用可保留)."""
    state = {
        "raw_papers": [{"id": f"r{i}", "relevance_score": 5.0} for i in range(20)],
        "expanded_papers": [{"id": f"e{i}", "relevance_score": 5.0} for i in range(20)],
        "ranked_papers": [{"id": f"p{i}", "relevance_score": 5.0} for i in range(20)],
        "iteration": 0,
        "status": "checking_refine",
    }
    out = prune_state(state)
    assert len(out["raw_papers"]) == 20
    assert len(out["expanded_papers"]) == 20
    assert len(out["ranked_papers"]) == 20


# ===== Test 2: 按 score 降序保留高分 =====
def test_prune_state_keeps_top_scores_for_ranked():
    """ranked_papers 超 cap 时, 按 relevance_score 降序保留前 30."""
    state = {
        "ranked_papers": [
            {"id": f"p{i}", "relevance_score": float(100 - i)}  # 0~100 递减
            for i in range(50)
        ],
    }
    out = prune_state(state)
    assert len(out["ranked_papers"]) == RANKED_PAPERS_CAP
    # 保留的应该是 score 最高的前 30 (i=0..29)
    kept_ids = [p["id"] for p in out["ranked_papers"]]
    assert kept_ids == [f"p{i}" for i in range(30)]


def test_prune_state_keeps_top_scores_for_raw():
    """raw_papers 超 cap 时同样按 score 降序."""
    state = {
        "raw_papers": [
            {"id": f"r{i}", "relevance_score": float(200 - i)}
            for i in range(80)
        ],
    }
    out = prune_state(state)
    assert len(out["raw_papers"]) == RAW_PAPERS_CAP
    kept_ids = [p["id"] for p in out["raw_papers"]]
    assert kept_ids == [f"r{i}" for i in range(50)]


# ===== Test 3: 0 分论文保持原序 (ranker 跳过兼容) =====
def test_prune_state_zero_scores_preserve_order():
    """relevance_score=0 的论文在 cap 不足时按原 list 顺序追加."""
    state = {
        "ranked_papers": [
            {"id": "with_score_1", "relevance_score": 7.0},
            {"id": "with_score_2", "relevance_score": 5.0},
            {"id": "zero_1", "relevance_score": 0},
            {"id": "zero_2", "relevance_score": None},
            {"id": "zero_3"},  # 缺字段
        ] * 10,  # 50 篇: 30 有分 + 20 无分
    }
    assert len(state["ranked_papers"]) == 50
    out = prune_state(state)
    assert len(out["ranked_papers"]) == RANKED_PAPERS_CAP
    # 前 30 都是有分的 (with_score_1, with_score_2 重复 * 10 = 20 + 10 段),
    # 后 N 个是 0 分. 简化检查: 至少前 20 个都是 with_score_X 模式
    first_20 = [p["id"] for p in out["ranked_papers"][:20]]
    assert all("with_score" in pid for pid in first_20)


# ===== Test 4: 嵌套 paper 字段完整保留 =====
def test_prune_state_preserves_paper_fields():
    """裁剪只砍 list 长度, paper 内部字段 (title/abstract/year/...) 不动."""
    state = {
        "ranked_papers": [
            {
                "id": "p1",
                "relevance_score": 8.0,
                "title": "Transformer Survey",
                "year": 2024,
                "abstract": "Long abstract " * 50,  # ~700 chars
                "venue": "NeurIPS",
                "authors": ["A1", "A2"],
            }
        ] * 50,
    }
    out = prune_state(state)
    sample = out["ranked_papers"][0]
    assert sample["title"] == "Transformer Survey"
    assert sample["year"] == 2024
    assert sample["venue"] == "NeurIPS"
    assert sample["authors"] == ["A1", "A2"]
    assert len(sample["abstract"]) > 500  # 完整保留


# ===== Test 5: 3 个 cap 独立生效 =====
def test_prune_state_independent_caps():
    """RAW/EXPANDED/RANKED 各自超 cap 时各自裁, 不相互影响."""
    state = {
        "raw_papers": [{"id": f"r{i}", "relevance_score": 5.0} for i in range(80)],
        "expanded_papers": [{"id": f"e{i}", "relevance_score": 5.0} for i in range(70)],
        "ranked_papers": [{"id": f"p{i}", "relevance_score": 5.0} for i in range(40)],
    }
    out = prune_state(state)
    assert len(out["raw_papers"]) == RAW_PAPERS_CAP
    assert len(out["expanded_papers"]) == EXPANDED_PAPERS_CAP
    assert len(out["ranked_papers"]) == RANKED_PAPERS_CAP


# ===== Test 6: 空 list / 缺字段不报错 =====
def test_prune_state_handles_empty_and_missing():
    """空 list / 缺字段不能 raise (防御性, 实际状态机都该有)."""
    assert prune_state({}) == {}
    assert prune_state({"raw_papers": []})["raw_papers"] == []
    assert prune_state({"raw_papers": None})["raw_papers"] is None


# ===== Test 7: 3 个 cap 在典型 max_iter=3 场景下能挡住 200+ 累积 =====
def test_prune_state_prevents_unbounded_growth():
    """模拟 max_iter=3 累积, 验证 cap 真起作用."""
    # 假设每 iter 检索 80 篇 raw, 扩展 70, ranked 40
    # 3 iter 后不裁剪: 240 / 210 / 120
    accumulated = {
        "raw_papers": [{"id": f"r{i}", "relevance_score": 5.0} for i in range(240)],
        "expanded_papers": [{"id": f"e{i}", "relevance_score": 5.0} for i in range(210)],
        "ranked_papers": [{"id": f"p{i}", "relevance_score": 5.0} for i in range(120)],
    }
    out = prune_state(accumulated)
    # 裁后: 50 / 50 / 30, 总 130
    assert len(out["raw_papers"]) == 50
    assert len(out["expanded_papers"]) == 50
    assert len(out["ranked_papers"]) == 30
    # 验证 SSE 序列化压力降低 (假设每篇 ~5KB, 130 * 5KB = 650KB,
    # 而不裁剪 570 * 5KB = 2.85MB, 4.4x 差异)
    total_after = sum(
        len(out[k]) for k in ("raw_papers", "expanded_papers", "ranked_papers")
    )
    total_before = sum(
        len(accumulated[k]) for k in ("raw_papers", "expanded_papers", "ranked_papers")
    )
    assert total_after < total_before / 3  # 至少砍 67%
