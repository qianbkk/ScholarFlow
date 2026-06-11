"""R10.5.9 防御性测试: graph_builder 兜底路径 warning log.

R10.5.8 code-review 修复: detect_communities_modularity 4 个 fallback 路径
(N<3, 无边, networkx 缺失, 异常) 之前都静默返单社区, 不可见.
本测试验证每个 fallback 都有 warning 输出.

为什么需要测试: warning log 容易在重构中被删, 而它是 dev 唯一可见的
"为什么我的图谱只有 1 个社区" 信号.
"""
from __future__ import annotations

import logging

import pytest

from backend.agents.graph_builder import detect_communities_modularity


def test_n_lt_3_logs_warning(caplog):
    """N<3 应触发 warning (R10.5.8)."""
    with caplog.at_level(logging.WARNING, logger="backend.agents.graph_builder"):
        result = detect_communities_modularity(["a", "b"], [])
    assert result == {"a": 0, "b": 0}
    assert any("community detection skipped" in r.message for r in caplog.records), (
        f"N<3 应有 warning, got: {[r.message for r in caplog.records]}"
    )


def test_no_edges_logs_warning(caplog):
    """无边 (但 N>=3) 应触发 warning."""
    with caplog.at_level(logging.WARNING, logger="backend.agents.graph_builder"):
        result = detect_communities_modularity(
            ["a", "b", "c"],
            [],  # 空 edges
        )
    assert result == {"a": 0, "b": 0, "c": 0}
    assert any("no edges" in r.message for r in caplog.records)


def test_greedy_modularity_exception_logs_warning(caplog, monkeypatch):
    """greedy_modularity_communities 抛异常 → 兜底单社区 + warning."""
    # 强制让 networkx.community.greedy_modularity_communities 抛错
    import networkx as nx
    from networkx import community as nx_community

    def boom(*args, **kwargs):
        raise RuntimeError("simulated networkx failure")

    monkeypatch.setattr(nx_community, "greedy_modularity_communities", boom)

    with caplog.at_level(logging.WARNING, logger="backend.agents.graph_builder"):
        result = detect_communities_modularity(
            ["a", "b", "c", "d"],
            [("a", "b", "cites"), ("c", "d", "cites")],
        )
    assert all(v == 0 for v in result.values()), "异常时所有节点都应回 0"
    assert any("simulated networkx failure" in r.message for r in caplog.records)


def test_node_ids_accepts_set():
    """R10.5.8: node_ids 兼容 set 输入 (原是 list, O(N) 检查 → O(1))."""
    # 应不抛错, 且正确识别 4 节点
    result = detect_communities_modularity(
        {"x", "y", "z", "w"},
        [("x", "y", "cites"), ("z", "w", "cites")],
    )
    assert len(result) == 4
    assert all(pid in result for pid in ["x", "y", "z", "w"])


def test_node_ids_list_still_works():
    """R10.5.8: 向后兼容 list 输入."""
    result = detect_communities_modularity(
        ["x", "y", "z", "w"],
        [("x", "y", "cites"), ("z", "w", "cites")],
    )
    assert len(result) == 4
