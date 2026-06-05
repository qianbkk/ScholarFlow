"""Tests for C5: API failure silent fallback to mock should be marked.

When the Semantic Scholar or OpenAlex API fails (timeout, 503, etc.) the
code falls back to mock data. Previously there was NO marker — the user
got a 200 response indistinguishable from a real successful call. This
test verifies that returned papers now have `is_fallback=True` set on the
fallback path.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


# ===== Paper model: is_fallback field =====

def test_paper_default_is_fallback_false():
    """Paper dataclass default is_fallback=False."""
    from backend.models.paper import Paper
    p = Paper()
    assert p.is_fallback is False


def test_paper_to_dict_includes_is_fallback():
    """Paper.to_dict() must include is_fallback field."""
    from backend.models.paper import Paper
    p = Paper(paper_id="x", title="T", is_fallback=True)
    d = p.to_dict()
    assert "is_fallback" in d, f"is_fallback not in to_dict output: {d.keys()}"
    assert d["is_fallback"] is True


def test_paper_from_dict_recovers_is_fallback():
    """Paper.from_dict() must recover is_fallback field from dict."""
    from backend.models.paper import Paper
    d = {"paper_id": "x", "title": "T", "is_fallback": True}
    p = Paper.from_dict(d)
    assert p.is_fallback is True


# ===== Semantic Scholar fallback path =====

def test_ss_search_papers_marks_fallback_on_500(monkeypatch):
    """When SS API returns 500, fallback papers must have is_fallback=True."""
    import backend.api.semantic_scholar as ss

    # Force "real" mode (not API_MOCK)
    monkeypatch.setattr(ss, "API_MOCK", False)

    # Mock _get_with_retry to return a 500 response
    fake_response = MagicMock()
    fake_response.status_code = 500

    async def fake_get_with_retry(*args, **kwargs):
        return fake_response

    monkeypatch.setattr(ss, "_get_with_retry", fake_get_with_retry)

    papers = asyncio.run(ss.search_papers("transformer", limit=3))
    assert len(papers) > 0, "Fallback should have returned mock papers"
    for p in papers:
        assert p.is_fallback is True, (
            f"Paper {p.paper_id!r} from SS fallback is missing is_fallback=True. "
            f"paper: {p}"
        )


def test_ss_search_papers_marks_fallback_on_exception(monkeypatch):
    """When SS API raises (network error), fallback papers must be marked."""
    import backend.api.semantic_scholar as ss

    monkeypatch.setattr(ss, "API_MOCK", False)

    async def fake_get_with_retry(*args, **kwargs):
        raise httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(ss, "_get_with_retry", fake_get_with_retry)

    papers = asyncio.run(ss.search_papers("transformer", limit=3))
    assert len(papers) > 0
    for p in papers:
        assert p.is_fallback is True


def test_ss_search_papers_api_mock_returns_no_fallback_marker(force_mock_api):
    """When in pure API_MOCK mode (not a real-API fallback), is_fallback stays False.

    The is_fallback flag is specifically for the 'real API failed, fell back to
    mock' path. In pure API_MOCK mode (env flag), the user explicitly opted
    into mock data, so no warning is needed.
    """
    import backend.api.semantic_scholar as ss
    papers = asyncio.run(ss.search_papers("transformer", limit=3))
    assert len(papers) > 0
    for p in papers:
        # In pure mock mode, the flag should remain at its default
        assert p.is_fallback is False, (
            f"Paper {p.paper_id!r} from pure API_MOCK mode should not have is_fallback=True"
        )


# ===== OpenAlex fallback path =====

def test_openalex_search_papers_marks_fallback_on_500(monkeypatch):
    """When OpenAlex API returns 500, fallback papers must have is_fallback=True."""
    import backend.api.openalex as oa

    monkeypatch.setattr(oa, "API_MOCK", False)

    fake_response = MagicMock()
    fake_response.status_code = 503

    async def fake_get_with_retry(*args, **kwargs):
        return fake_response

    monkeypatch.setattr(oa, "_get_with_retry", fake_get_with_retry)

    # Use a query that matches OpenAlex mock papers (e.g. "neural network")
    papers = asyncio.run(oa.search_papers("neural network", limit=5))
    assert len(papers) > 0, "Fallback should have returned mock papers"
    for p in papers:
        assert p.is_fallback is True, (
            f"Paper {p.paper_id!r} from OpenAlex fallback is missing is_fallback=True. "
            f"paper: {p}"
        )


def test_openalex_search_papers_marks_fallback_on_exception(monkeypatch):
    """When OpenAlex API raises, fallback papers must be marked."""
    import backend.api.openalex as oa

    monkeypatch.setattr(oa, "API_MOCK", False)

    async def fake_get_with_retry(*args, **kwargs):
        raise httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(oa, "_get_with_retry", fake_get_with_retry)

    papers = asyncio.run(oa.search_papers("neural network", limit=5))
    assert len(papers) > 0
    for p in papers:
        assert p.is_fallback is True
