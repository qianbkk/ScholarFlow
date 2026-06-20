"""R10.5.39 Phase 1.1 — multi-source search.

Verifies the 3 new clients (arXiv, Crossref, PubMed) parse correctly under
mock mode and that search_agent respects SCHOLARFLOW_SOURCES env var.

Tests run entirely offline (mock mode), no real API calls.
"""
from __future__ import annotations

import asyncio
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ===== arXiv parser =====

def test_arxiv_make_paper_minimal():
    """arXiv Atom <entry> -> Paper with id, title, year, authors, abstract."""
    from backend.api import arxiv

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<entry xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <id>http://arxiv.org/abs/2401.01234v1</id>
  <title>Test Paper Title</title>
  <summary>This is the abstract.</summary>
  <published>2024-01-15T00:00:00Z</published>
  <author><name>Alice Smith</name></author>
  <author><name>Bob Jones</name></author>
  <arxiv:doi>10.1234/test</arxiv:doi>
  <arxiv:journal_ref>Nature 2024</arxiv:journal_ref>
</entry>"""
    entry = ET.fromstring(xml)
    p = arxiv._make_paper(entry)
    assert p is not None
    assert p.paper_id == "arxiv_2401.01234"
    assert p.title == "Test Paper Title"
    assert p.year == 2024
    assert p.abstract == "This is the abstract."
    assert p.authors == ["Alice Smith", "Bob Jones"]
    assert p.doi == "10.1234/test"
    assert p.venue == "Nature 2024"
    assert p.url == "http://arxiv.org/abs/2401.01234v1"


def test_arxiv_make_paper_collapses_whitespace_in_title():
    """arXiv titles often have wrapped whitespace; should be collapsed."""
    from backend.api import arxiv

    xml = """<?xml version="1.0"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <id>http://arxiv.org/abs/2402.99999v2</id>
  <title>  Multi
  line
  title  </title>
  <summary>abs</summary>
  <published>2024-02-01T00:00:00Z</published>
</entry>"""
    entry = ET.fromstring(xml)
    p = arxiv._make_paper(entry)
    assert p is not None
    assert p.title == "Multi line title"
    assert p.year == 2024


def test_arxiv_make_paper_handles_missing_optional_fields():
    """Missing DOI, journal_ref, authors should not crash."""
    from backend.api import arxiv

    xml = """<?xml version="1.0"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <id>http://arxiv.org/abs/9999.00000v1</id>
  <title>Bare Paper</title>
  <summary>abs</summary>
  <published>2025-06-01T00:00:00Z</published>
</entry>"""
    entry = ET.fromstring(xml)
    p = arxiv._make_paper(entry)
    assert p is not None
    assert p.doi is None
    assert p.venue == "arXiv"
    assert p.authors == []


def test_arxiv_search_papers_mock_returns_empty():
    """In mock mode arxiv should return [] (no real call)."""
    from backend.api import arxiv
    from backend.utils import runtime_mode

    # Force mock mode
    # R10.5.51 cleanup (BACKLOG D-007): 改用显式 set_runtime_mode API
    # (旧 dict-subclass proxy _runtime_mode_override 已删)
    runtime_mode.set_runtime_mode("mock")
    runtime_mode._invalidate_cache()
    try:
        result = asyncio.run(arxiv.search_papers("anything", limit=5))
        assert result == []
    finally:
        runtime_mode.set_runtime_mode("auto")
        runtime_mode._invalidate_cache()


# ===== Crossref parser =====

def test_crossref_make_paper_minimal():
    """Crossref work -> Paper."""
    from backend.api import crossref

    item = {
        "DOI": "10.1234/test",
        "title": ["Crossref Paper"],
        "abstract": "<jats:p>An abstract.</jats:p>",
        "author": [{"given": "Alice", "family": "Smith"}],
        "container-title": ["Nature"],
        "publisher": "Nature Publishing",
        "published-print": {"date-parts": [[2023, 6, 1]]},
        "is-referenced-by-count": 42,
        "URL": "https://doi.org/10.1234/test",
    }
    p = crossref._make_paper(item)
    assert p is not None
    assert p.paper_id == "cr_10.1234_test"
    assert p.title == "Crossref Paper"
    assert p.year == 2023
    assert p.abstract == "An abstract."  # JATS stripped
    assert p.authors == ["Alice Smith"]
    assert p.citation_count == 42
    assert "Nature" in p.venue
    assert p.doi == "10.1234/test"


def test_crossref_make_paper_strips_jats_xml():
    """Crossref abstracts with JATS XML should be cleaned."""
    from backend.api import crossref

    item = {
        "DOI": "10.x/y",
        "title": ["X"],
        "abstract": "<jats:p>Para 1.</jats:p> <jats:p>Para 2.</jats:p>",
        "published-print": {"date-parts": [[2022]]},
    }
    p = crossref._make_paper(item)
    assert p is not None
    assert "<" not in p.abstract
    assert "Para 1" in p.abstract and "Para 2" in p.abstract


def test_crossref_make_paper_no_doi():
    """No DOI -> fallback paper_id, no url break."""
    from backend.api import crossref

    item = {
        "title": ["No DOI Paper"],
        "published-print": {"date-parts": [[2020]]},
    }
    p = crossref._make_paper(item)
    assert p is not None
    assert p.paper_id.startswith("cr_")
    assert p.doi is None


def test_crossref_search_papers_mock_returns_empty():
    from backend.api import crossref
    from backend.utils import runtime_mode

    runtime_mode.set_runtime_mode("mock")
    runtime_mode._invalidate_cache()
    try:
        result = asyncio.run(crossref.search_papers("anything", limit=5))
        assert result == []
    finally:
        runtime_mode.set_runtime_mode("auto")
        runtime_mode._invalidate_cache()


# ===== PubMed parser =====

def test_pubmed_make_paper_minimal():
    """PubMed esummary doc -> Paper."""
    from backend.api import pubmed

    doc = {
        "uid": "12345678",
        "title": "PubMed Paper",
        "pubdate": "2023 Jun 15",
        "fulljournalname": "Cell",
        "source": "Cell",
        "abstract": "This is the abstract.",
        "authors": [{"name": "Smith AB", "authtype": "Author"}],
        "articleids": [
            {"idtype": "doi", "value": "10.1234/pm"},
            {"idtype": "pmc", "value": "PMC9999999"},
        ],
    }
    p = pubmed._make_paper("12345678", doc)
    assert p is not None
    assert p.paper_id == "pm_12345678"
    assert p.title == "PubMed Paper"
    assert p.year == 2023
    assert p.venue == "Cell"
    assert p.authors == ["Smith AB"]  # PubMed esummary returns "Lastname Initials"
    assert p.doi == "10.1234/pm"
    assert "pmc/articles/PMC9999999" in p.url


def test_pubmed_make_paper_handles_garbage_year():
    """Bad pubdate -> year=0, don't crash."""
    from backend.api import pubmed

    doc = {
        "uid": "1",
        "title": "X",
        "pubdate": "Preprint",
        "authors": [],
        "articleids": [],
    }
    p = pubmed._make_paper("1", doc)
    assert p is not None
    assert p.year == 0


def test_pubmed_search_papers_mock_returns_empty():
    from backend.api import pubmed
    from backend.utils import runtime_mode

    runtime_mode.set_runtime_mode("mock")
    runtime_mode._invalidate_cache()
    try:
        result = asyncio.run(pubmed.search_papers("anything", limit=5))
        assert result == []
    finally:
        runtime_mode.set_runtime_mode("auto")
        runtime_mode._invalidate_cache()


# ===== search_agent source selection =====

def test_search_agent_respects_sources_env_var(monkeypatch):
    """SCHOLARFLOW_SOURCES env var should prune the source list."""
    # Force only SS+OA
    monkeypatch.setenv("SCHOLARFLOW_SOURCES", "ss,oa")
    # Reload search_agent to pick up env var
    import importlib
    import backend.agents.search_agent
    importlib.reload(backend.agents.search_agent)
    coros = backend.agents.search_agent._get_search_coros("test", limit=5)
    names = [n for n, _ in coros]
    assert names == ["ss", "oa"]

    # Force all 5
    monkeypatch.setenv("SCHOLARFLOW_SOURCES", "ss,oa,arxiv,crossref,pubmed")
    importlib.reload(backend.agents.search_agent)
    coros = backend.agents.search_agent._get_search_coros("test", limit=5)
    names = [n for n, _ in coros]
    assert names == ["ss", "oa", "arxiv", "crossref", "pubmed"]

    # Single source
    monkeypatch.setenv("SCHOLARFLOW_SOURCES", "arxiv")
    importlib.reload(backend.agents.search_agent)
    coros = backend.agents.search_agent._get_search_coros("test", limit=5)
    names = [n for n, _ in coros]
    assert names == ["arxiv"]

    # Restore default for next tests
    monkeypatch.delenv("SCHOLARFLOW_SOURCES", raising=False)
    importlib.reload(backend.agents.search_agent)
