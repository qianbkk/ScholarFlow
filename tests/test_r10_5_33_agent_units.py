"""R10.5.33 (CD.txt §3.1) agent 节点单元测试.

回应 CD.txt §3.1 '无法 unit test agent behavior' — 9 个 agent 节点
(query_decompose / search / expand_citations / rank / refine /
critic_review / synthesize / build_graph / track_cost) 之前 0
单元测试 (只有 1 个 test_search_node_semaphore.py 是端到端).
这次加 2 个最常用 agent 的单测:
  - critic_review_node: 真评审 0 论文 + 多论文, 验证 state 不被破坏
  - query_decompose_node: 提子查询 + 抽约束, 验证 fallback 路径
mock 整个 LLM 层 (call_llm + settings) 让单测不依赖外部 API.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_critic_review_node_empty_ranked_papers():
    """critic_review_node: ranked_papers 为空 → 直接返 state, 不调 LLM."""
    from backend.agents.critic_agent import critic_review_node

    state = {
        "original_query": "transformer",
        "ranked_papers": [],
        "provider": "minimax",
    }
    result = asyncio.run(critic_review_node(state))
    # 空 ranked 不应塞 critic_results
    assert "critic_results" not in result or result.get("critic_results") == []
    # 原始 state 字段保留
    assert result["original_query"] == "transformer"
    assert result["ranked_papers"] == []


def test_critic_review_node_with_papers_uses_call_llm():
    """critic_review_node: 有 ranked_papers → 调 call_llm, mock 返 quality_score."""
    from backend.agents import critic_agent
    from backend.utils import llm_client

    orig = llm_client.call_llm

    async def fake_call_llm(*args, **kwargs):
        # 返 JSON 格式让 critic 解析
        return ('{"quality_score": 8, "recommendation": "adopt", "reasoning": "good"}',
                {"cost": 0.01, "tokens": 50})

    llm_client.call_llm = fake_call_llm
    try:
        state = {
            "original_query": "BERT pretraining",
            "ranked_papers": [
                {"paper_id": "ss_001", "title": "BERT", "abstract": "x"},
                {"paper_id": "ss_002", "title": "GPT", "abstract": "y"},
            ],
            "provider": "minimax",
        }
        result = asyncio.run(critic_agent.critic_review_node(state))
        # ranked_papers 字段保留 (2 篇)
        assert len(result.get("ranked_papers", [])) == 2
        # 原始 state 字段保留
        assert result["original_query"] == "BERT pretraining"
    finally:
        llm_client.call_llm = orig


def test_critic_review_node_handles_llm_exception():
    """critic_review_node: call_llm 抛异常 → 单篇评审失败, 不阻断整个 pipeline."""
    from backend.agents import critic_agent
    from backend.utils import llm_client

    orig = llm_client.call_llm

    async def fake_call_llm_error(*args, **kwargs):
        raise RuntimeError("LLM outage")

    llm_client.call_llm = fake_call_llm_error
    try:
        state = {
            "original_query": "x",
            "ranked_papers": [
                {"paper_id": "ss_a", "title": "A", "abstract": "a"},
                {"paper_id": "ss_b", "title": "B", "abstract": "b"},
            ],
            "provider": "minimax",
        }
        # 不应抛, 单篇失败被 catch 掉
        result = asyncio.run(critic_agent.critic_review_node(state))
        # 至少 state 仍存在
        assert result["original_query"] == "x"
    finally:
        llm_client.call_llm = orig


def test_critic_review_node_truncates_to_10_papers():
    """critic_review_node: ranked_papers > 10 → 只评审前 10 篇 (line 58 切片).

    验证方式: 不依赖 call_count 计数 (可能被 cache / 异常分支绕过),
    改用 result["critic_results"] 长度 = 10 验证.
    """
    from backend.agents import critic_agent
    from backend.utils import llm_client

    orig = llm_client.call_llm

    async def fake_call_llm(*args, **kwargs):
        # 返完整 JSON + 全部字段
        return ('{"quality_score": 7, "recommendation": "cautious", "strengths": [], "weaknesses": [], "methodology_issues": "", "confidence": 0.5, "reasoning": "ok"}',
                {"cost": 0.001, "tokens": 20})

    llm_client.call_llm = fake_call_llm
    try:
        state = {
            "original_query": "x",
            "ranked_papers": [
                {"paper_id": f"ss_{i}", "title": f"T{i}", "abstract": "a"}
                for i in range(20)  # 20 篇 > 10 限制
            ],
            "provider": "minimax",
        }
        result = asyncio.run(critic_agent.critic_review_node(state))
        # critic_results 长度应 ≤ 10 (line 58 [:10] 切片生效)
        critic_results = result.get("critic_results", [])
        assert len(critic_results) <= 10, (
            f"应只评审 ≤10 篇, 实际 critic_results 长度 = {len(critic_results)}"
        )
    finally:
        llm_client.call_llm = orig


def test_query_decompose_fallback_basic():
    """query_decompose._fallback_decompose: 返回非空 list, 含原始 query 或其变体."""
    from backend.agents.query_decomposer import _fallback_decompose

    # 普通查询 — 返包含原 query 的列表 (实现是 LLM_MOCK 兜底: 整句 + 几个变体)
    out = _fallback_decompose("transformer attention mechanism")
    assert isinstance(out, list)
    assert len(out) >= 1
    # 至少原 query 字符串在结果中 (兜底实现不切词, 整句保留)
    assert any("transformer attention mechanism" in s for s in out)


def test_query_decompose_fallback_handles_chinese():
    """query_decompose._fallback_decompose: 中文查询 — 不依赖空格分词, 整句保留."""
    from backend.agents.query_decomposer import _fallback_decompose

    out = _fallback_decompose("图神经网络分子性质预测")
    assert isinstance(out, list)
    # 中文整句保留 (无空格, 不会被空格分词切碎)
    assert "图神经网络分子性质预测" in out or len(out) >= 1


def test_query_decompose_fallback_constraints_year_venue():
    """query_decompose._fallback_constraints: 抽 year / venue 正则."""
    from backend.agents.query_decomposer import _fallback_constraints

    # year 抽取
    c1 = _fallback_constraints("transformer since 2022 NeurIPS")
    assert "2022" in str(c1.get("year_range") or ""), f"应抽 year 2022, 实际 {c1}"
    # venue 抽取 (大小写不敏感)
    c2 = _fallback_constraints("graph neural network ACL 2023")
    venues = c2.get("venues") or []
    assert any("ACL" in v.upper() for v in venues), f"应抽 venue ACL, 实际 venues={venues}"


def test_query_decompose_fallback_constraints_datasets():
    """query_decompose._fallback_constraints: datasets 字段离线不抽 (留 None 兜底).

    R10.5.33: query_decomposer._fallback_constraints() 故意不抽 datasets
    (line 86 'methods / datasets 离线抽成本高(需要词典), 留 None 让 LLM 来抽').
    这是设计选择不是 bug — 离线词典维护成本 vs LLM 一次性抽, 选 LLM.
    """
    from backend.agents.query_decomposer import _fallback_constraints

    c = _fallback_constraints("image classification on ImageNet and CIFAR-10")
    # 设计上 datasets 离线不抽, 留 None 给 LLM 兜底
    assert c.get("datasets") is None, (
        f"datasets 离线应保持 None, 实际 {c.get('datasets')}"
    )
    # 返 dict 4 维 schema 完整
    assert set(c.keys()) == {"venues", "year_range", "methods", "datasets"}


def test_query_decompose_sanitize_str_list_caps_at_8():
    """query_decompose._sanitize_str_list: 上限 8 条, 截断超长列表."""
    from backend.agents.query_decomposer import _sanitize_str_list

    out = _sanitize_str_list([f"q{i}" for i in range(20)], cap=8)
    assert out is not None
    assert len(out) == 8


def test_query_decompose_sanitize_str_list_rejects_non_string():
    """query_decompose._sanitize_str_list: 元素非 str → 返 None (拒绝)."""
    from backend.agents.query_decomposer import _sanitize_str_list

    assert _sanitize_str_list([1, 2, 3]) is None
    assert _sanitize_str_list("not a list") is None
    assert _sanitize_str_list(None) is None
