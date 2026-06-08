"""Tests for graph_builder.build_graph_node — 4 类边 + 节点 metadata.

X-9 报告: 8 节点中 graph_builder 0 单测. 4 类边 (cites/co_cited/same_venue/
author_overlap) 是 ScholarFlow 跟 ResearchRabbit 差异化点, 必须有回归保护.
"""
from __future__ import annotations

import pytest

from backend.agents.graph_builder import build_graph_node


def _paper(pid: str, **kwargs) -> dict:
    base = {
        "paper_id": pid,
        "title": f"Paper {pid}",
        "abstract": "x" * 200,
        "year": kwargs.get("year", 2020),
        "authors": kwargs.get("authors", ["Alice", "Bob"]),
        "venue": kwargs.get("venue", "NeurIPS"),
        "citation_count": kwargs.get("citation_count", 50),
        "relevance_score": kwargs.get("relevance_score", 7.0),
        "final_score": kwargs.get("final_score", 7.0),
        "references": kwargs.get("references", []),
    }
    return base


class TestFourEdgeTypes:
    """M-18 4 类边都正确生成."""

    def test_cites_edge_from_references(self):
        """paper A.references 含 B → cites 边 A → B."""
        ranked = [
            _paper("a", references=["b"]),
            _paper("b"),
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        graph = result["citation_graph"]
        link_types = {l["type"] for l in graph["links"]}
        assert "cites" in link_types
        # A → B
        cites_to_b = [
            (l["source"], l["target"]) for l in graph["links"]
            if l["type"] == "cites"
        ]
        assert ("a", "b") in cites_to_b

    def test_co_cited_edge_when_shared_references(self):
        """A 和 B 都有 references 包含 C 和 D → co_cited 边."""
        ranked = [
            _paper("a", references=["c", "d"]),
            _paper("b", references=["c", "d"]),
            _paper("c"),
            _paper("d"),
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        graph = result["citation_graph"]
        link_types = {l["type"] for l in graph["links"]}
        assert "co_cited" in link_types

    def test_same_venue_edge(self):
        """同 venue 2 篇以上 (且 <=6) → same_venue 边."""
        ranked = [
            _paper("a", venue="ICML"),
            _paper("b", venue="ICML"),
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        graph = result["citation_graph"]
        link_types = {l["type"] for l in graph["links"]}
        assert "same_venue" in link_types

    def test_author_overlap_edge(self):
        """两篇有共同作者 → author_overlap 边."""
        ranked = [
            _paper("a", authors=["Alice", "Bob"]),
            _paper("b", authors=["Alice", "Charlie"]),
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        graph = result["citation_graph"]
        link_types = {l["type"] for l in graph["links"]}
        assert "author_overlap" in link_types


class TestNodeMetadata:
    """节点 metadata: in_degree / out_degree / pagerank / community_id."""

    def test_in_degree_counts_cites_in(self):
        """A 引用 C, B 引用 C → C.in_degree = 2."""
        ranked = [
            _paper("a", references=["c"]),
            _paper("b", references=["c"]),
            _paper("c"),
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        graph = result["citation_graph"]
        c_node = next(n for n in graph["nodes"] if n["id"] == "c")
        assert c_node["in_degree"] == 2
        assert c_node["out_degree"] == 0

    def test_pagerank_normalized_to_1(self):
        """pagerank 归一化: max in_degree 节点 pagerank ≈ 1.0."""
        ranked = [
            _paper("a", references=["c"]),
            _paper("b", references=["c"]),
            _paper("c", references=["d"]),
            _paper("d"),
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        graph = result["citation_graph"]
        c_node = next(n for n in graph["nodes"] if n["id"] == "c")
        # c 被 a + b 引用, in_degree=2, max_in_degree=2, pagerank=1.0
        assert c_node["pagerank"] == 1.0

    def test_community_id_by_decade(self):
        """community_id 按 decade 分组 (2010s 同社区)."""
        ranked = [
            _paper("a", year=2015),
            _paper("b", year=2018),
            _paper("c", year=1995),
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        graph = result["citation_graph"]
        # 2010s: a, b 同 decade → 同 community
        a_node = next(n for n in graph["nodes"] if n["id"] == "a")
        b_node = next(n for n in graph["nodes"] if n["id"] == "b")
        c_node = next(n for n in graph["nodes"] if n["id"] == "c")
        assert a_node["community_id"] == b_node["community_id"]
        assert a_node["community_id"] != c_node["community_id"]


class TestGraphMetadata:
    """metadata 字段: year_range / link_type_counts / community_count."""

    def test_metadata_year_range(self):
        ranked = [
            _paper("a", year=2015),
            _paper("b", year=2020),
            _paper("c", year=2018),
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        meta = result["citation_graph"]["metadata"]
        # year_range 是 [min, max] 列表
        assert meta["year_range"][0] == 2015
        assert meta["year_range"][1] == 2020

    def test_metadata_link_type_counts(self):
        """metadata 统计 4 类边各自的条数."""
        ranked = [
            _paper("a", references=["b"], venue="ICML"),
            _paper("b", venue="ICML", authors=["Alice"]),
            _paper("c", references=["a", "b"]),  # 触发 cites + co_cited
        ]
        state = {"ranked_papers": ranked}
        result = build_graph_node(state)
        meta = result["citation_graph"]["metadata"]
        assert "cites" in meta["link_type_counts"]
        assert "same_venue" in meta["link_type_counts"]


class TestEmptyRanked:
    """边界: ranked_papers 空."""

    def test_empty_ranked_returns_empty_graph(self):
        state = {"ranked_papers": []}
        result = build_graph_node(state)
        graph = result["citation_graph"]
        assert graph["nodes"] == []
        assert graph["links"] == []
