"""Smoke test for backend.shared package.

Verifies:
  - `from backend.shared import Paper, PipelineState, NodeId` works
  - Paper can be constructed and reads back the same title/year
  - NodeId literal values match the 8 expected node IDs
  - Identity re-export: backend.models.paper.Paper is backend.shared.Paper
"""
import typing

from backend.shared import Paper, PipelineState, NodeId


def test_paper_construction_roundtrip():
    paper = Paper(title="x", year=2020)
    assert paper.title == "x"
    assert paper.year == 2020
    # Defaults from the dataclass still hold
    assert paper.paper_id == ""
    assert paper.authors == []
    assert paper.relevance_score == 0.0
    assert paper._scored is False


def test_paper_to_from_dict_roundtrip():
    paper = Paper(title="x", year=2020, authors=["A. Author"])
    d = paper.to_dict()
    assert d["title"] == "x"
    assert d["authors"] == ["A. Author"]
    again = Paper.from_dict(d)
    assert again.title == "x"
    assert again.year == 2020
    assert again.authors == ["A. Author"]


def test_node_id_literal_values():
    expected = {
        "query_decomposer",
        "query_refiner",
        "paper_searcher",
        "relevance_scorer",
        "evidence_extractor",
        "gap_analyzer",
        "critic",
        "synthesis",
    }
    # typing.get_args returns the literal members for a Literal alias
    actual = set(typing.get_args(NodeId))
    assert actual == expected
    assert len(actual) == 8


def test_pipeline_state_keys():
    keys = set(PipelineState.__annotations__.keys())
    assert keys == {"query", "iteration", "status", "error"}


def test_paper_identity_with_models_paper():
    """Re-export shim: backend.models.paper.Paper is the same class."""
    import backend.models.paper as models_paper
    import backend.shared.paper_model as shared_paper_model

    # Both modules must re-export the same class object
    assert models_paper.Paper is shared_paper_model.Paper
    assert models_paper.Paper is Paper


def test_paper_source_literal_present():
    import backend.shared.paper_model as shared_paper_model

    members = set(typing.get_args(shared_paper_model.PaperSource))
    # Spot-check a couple of expected source names
    assert "semantic_scholar" in members
    assert "openalex" in members
    assert "synthesis" in members