"""Tests for CRITICAL-001: main.py cache call sites must pass provider=provider.

Background
----------
The cache module (`backend.utils.cache`) exposes `get_cached_async` /
`set_cached_async` with a `provider` kwarg that scopes the cache key
to the LLM provider (kimi / glm / anthropic / ...). If main.py calls
these without `provider=`, cache pollution can occur when a user
switches providers (e.g. kimi result served to anthropic user).

These tests verify that the /search and /search/stream call sites
ALWAYS pass `provider=` so the cache key correctly carries the
provider dimension.

Test strategy
-------------
We mock `get_cached_async` / `set_cached_async` on the `backend.main`
module's namespace and use `unittest.mock.patch` to inspect call
arguments after invoking the FastAPI endpoints. We use TestClient to
avoid the need for a running uvicorn server.
"""
import asyncio
import inspect
import time as _time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod
from backend.utils import cache as cache_mod


# ===== Fixtures =====

@pytest.fixture(autouse=True)
def _isolated_budget_db(monkeypatch, tmp_path):
    """Redirect budget + cache DBs to a temp file and seed the budget table."""
    db_path = tmp_path / "test_isolated_cache.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    # Reset init flag so the temp DB gets created.
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    # Seed budget so /search can reserve.
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 50.0)
    yield


@pytest.fixture
def fake_search_graph(monkeypatch):
    """Mock search_graph.ainvoke to return a minimal valid final state.

    Avoids running the real 8-node pipeline; the cache call sites are
    what we're testing, not the pipeline.
    """
    async def fake_ainvoke(initial):
        return {
            **initial,
            "report": "fake report",
            "ranked_papers": [],
            "citation_graph": {"nodes": [], "links": []},
            "total_cost_usd": 0.0,
            "total_tokens_used": 0,
            "model_usage": {},
            "iteration": 0,
            "status": "done",
        }

    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)
    return fake_ainvoke


@pytest.fixture
def client():
    """FastAPI TestClient."""
    return TestClient(main_mod.app)


# ===== 1) /search passes provider= to get_cached_async =====

def test_search_passes_provider_to_get_cached(client, fake_search_graph, monkeypatch):
    """/search must call get_cached_async with provider=provider kwarg."""
    # Replace get_cached_async with a tracking mock (must be async).
    captured = {}

    async def fake_get_cached(query, max_iterations, budget, ttl_seconds=None, provider=None):
        captured["query"] = query
        captured["max_iterations"] = max_iterations
        captured["budget"] = budget
        captured["provider"] = provider
        return None  # cache miss — force pipeline run

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    # Default provider (LLM_PROVIDER env → "kimi" in test env)
    resp = client.post(
        "/search",
        json={"query": "transformer attention", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 200, f"/search should succeed, got {resp.status_code}: {resp.text}"

    # The CRITICAL-001 assertion: get_cached_async was called with provider=
    assert "provider" in captured, (
        "CRITICAL-001 FAIL: get_cached_async was called without provider= kwarg. "
        "main.py /search must pass provider=provider so cache key is provider-scoped."
    )
    # provider must NOT be None — it should be a string (the resolved provider id)
    assert captured["provider"] is not None, (
        f"provider= must be the resolved provider id, got None. captured={captured}"
    )
    assert isinstance(captured["provider"], str), (
        f"provider= should be a string, got {type(captured['provider']).__name__}: "
        f"{captured['provider']!r}"
    )


# ===== 2) /search passes provider= to set_cached_async =====

def test_search_passes_provider_to_set_cached(client, fake_search_graph, monkeypatch):
    """/search must call set_cached_async with provider=provider kwarg."""
    captured = {}

    async def fake_set_cached(
        query, max_iterations, budget, response, cost_usd, tokens, provider=None
    ):
        captured["query"] = query
        captured["response"] = response
        captured["provider"] = provider
        captured["cost_usd"] = cost_usd
        captured["tokens"] = tokens
        return None

    # get_cached returns None to force pipeline run
    async def fake_get_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    resp = client.post(
        "/search",
        json={"query": "graph neural networks", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 200, f"/search failed: {resp.status_code} {resp.text}"

    # set_cached_async must have been called
    assert "provider" in captured, (
        "CRITICAL-001 FAIL: set_cached_async was called without provider= kwarg."
    )
    assert captured["provider"] is not None, (
        f"set_cached_async provider= must not be None, got: {captured.get('provider')!r}"
    )


# ===== 3) /search uses user-supplied provider when given =====

def test_search_uses_user_supplied_provider(client, fake_search_graph, monkeypatch):
    """When client sends provider=glm, /search must use 'glm' in cache call."""
    captured = {}

    async def fake_get_cached(query, max_iterations, budget, ttl_seconds=None, provider=None):
        captured["provider"] = provider
        return None

    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)

    # Need a provider that _resolve_provider accepts. In test env, _get_providers_with_keys()
    # falls back to LLM_PROVIDER="kimi" with has_key=True (env var present? actually not —
    # in test env _has_any_llm_key is empty, so LLM_MOCK auto-enables but env vars are empty
    # so has_key=False). So we need to mock the provider list.
    monkeypatch.setattr(
        main_mod,
        "_get_providers_with_keys",
        lambda: [
            {"id": "kimi", "has_key": True},
            {"id": "glm", "has_key": True},
            {"id": "anthropic", "has_key": True},
        ],
    )

    resp = client.post(
        "/search",
        json={
            "query": "deep learning",
            "max_iterations": 1,
            "budget": 0.5,
            "provider": "glm",
        },
    )
    assert resp.status_code == 200, f"/search failed: {resp.status_code} {resp.text}"

    # The provider passed to get_cached_async should be the user-supplied one.
    assert captured.get("provider") == "glm", (
        f"Provider should be 'glm' (user-supplied), got {captured.get('provider')!r}. "
        "main.py /search must resolve user provider and pass it to cache calls."
    )


# ===== 4) /search/stream passes provider= to get_cached_async =====

def test_stream_passes_provider_to_get_cached(client, fake_search_graph, monkeypatch):
    """/search/stream must also call get_cached_async with provider= kwarg."""
    captured = {}

    async def fake_get_cached(query, max_iterations, budget, ttl_seconds=None, provider=None):
        captured["query"] = query
        captured["provider"] = provider
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    # Also mock astream to be a no-op so we don't run the real pipeline
    async def fake_astream(*args, **kwargs):
        return
        yield  # Make it a generator (never reached)

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

    # Use a provider that's accepted by mocked _get_providers_with_keys
    monkeypatch.setattr(
        main_mod,
        "_get_providers_with_keys",
        lambda: [{"id": "kimi", "has_key": True}],
    )

    # TestClient with stream=True; we just need to confirm provider was captured
    with client.stream(
        "GET",
        "/search/stream",
        params={"q": "transformer", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
    ) as resp:
        # consume a bit of the response
        try:
            for _ in resp.iter_lines():
                # The streaming endpoint yields a 'started' event then iterates graph.
                # We stop early; capturing happens in mock.
                break
        except Exception:
            pass

    assert "provider" in captured, (
        "CRITICAL-001 FAIL: /search/stream called get_cached_async without provider= kwarg"
    )
    assert captured["provider"] == "kimi", (
        f"/search/stream should pass provider='kimi' to get_cached_async, "
        f"got {captured.get('provider')!r}"
    )


# ===== 5) call_args inspection (more rigorous variant) =====

def test_search_get_cached_call_args_kwarg_present(client, fake_search_graph, monkeypatch):
    """Inspect mock.call_args.kwargs to assert provider= was passed by name."""
    mock_get = AsyncMock(return_value=None)
    mock_set = AsyncMock()

    # Replace names in main module namespace
    monkeypatch.setattr(main_mod, "get_cached_async", mock_get)
    monkeypatch.setattr(main_mod, "set_cached_async", mock_set)

    resp = client.post(
        "/search",
        json={"query": "rosettafold", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 200, f"/search failed: {resp.status_code} {resp.text}"

    # Inspect get_cached_async call
    assert mock_get.await_count >= 1, "get_cached_async was not awaited"
    call = mock_get.call_args
    assert call is not None, "get_cached_async has no recorded call"

    # The call may use positional or keyword. Check the keyword argument is present.
    kwargs = call.kwargs if hasattr(call, "kwargs") else {}
    if "provider" not in kwargs:
        # Maybe positional? Inspect args.
        args = call.args if hasattr(call, "args") else ()
        # We can't easily map back to a name from positional; just assert it's not None in
        # the actual call site by checking the call_args_list exhaustively.
        # For this test, also check the most-recent call was non-None provider.
        pass

    # Primary assertion: kwargs includes 'provider'
    assert "provider" in kwargs, (
        f"CRITICAL-001 FAIL: get_cached_async was not called with provider= keyword. "
        f"call.args={call.args!r}, call.kwargs={kwargs!r}"
    )
    assert kwargs["provider"] is not None, (
        f"get_cached_async provider= should be a real provider id, got None. kwargs={kwargs!r}"
    )

    # Also inspect set_cached_async
    assert mock_set.await_count >= 1, "set_cached_async was not awaited"
    set_call = mock_set.call_args
    set_kwargs = set_call.kwargs if hasattr(set_call, "kwargs") else {}
    assert "provider" in set_kwargs, (
        f"CRITICAL-001 FAIL: set_cached_async was not called with provider= keyword. "
        f"call.args={set_call.args!r}, call.kwargs={set_kwargs!r}"
    )
    assert set_kwargs["provider"] is not None, (
        f"set_cached_async provider= should not be None, got {set_kwargs.get('provider')!r}"
    )


# ===== 6) Source-level guard (defensive) =====

def test_main_py_source_passes_provider_to_cache():
    """Static fallback: main.py's /search and /search/stream should pass
    `provider=` to get_cached_async and set_cached_async call sites.

    This guards against silent regressions in future refactors.
    """
    from pathlib import Path
    src_path = Path(main_mod.__file__)
    src = src_path.read_text(encoding="utf-8")

    # Find the cache call sites in the source.
    # We expect to see 'provider=provider' (or equivalent) at the call site.
    # The exact pattern is intentionally loose: get/set with provider= kwarg.
    # Allow either `provider=provider`, `provider=resolved_provider`, etc.
    # The call may span multiple lines, so we use a non-greedy match across newlines.
    import re
    has_provider_in_get = bool(
        re.search(
            r"get_cached_async\s*\([\s\S]*?provider\s*=", src
        )
    )
    has_provider_in_set = bool(
        re.search(
            r"set_cached_async\s*\([\s\S]*?provider\s*=", src
        )
    )

    assert has_provider_in_get, (
        "CRITICAL-001 FAIL: main.py must call get_cached_async with provider= kwarg. "
        "Search the source for `get_cached_async(` and verify provider= is passed."
    )
    assert has_provider_in_set, (
        "CRITICAL-001 FAIL: main.py must call set_cached_async with provider= kwarg. "
        "Search the source for `set_cached_async(` and verify provider= is passed."
    )


# ===== 7) Two different providers → two different cache keys (integration check) =====

def test_search_different_providers_use_different_cache_keys(
    client, fake_search_graph, monkeypatch
):
    """Two requests with different provider= should compute different cache keys
    at the cache module level.

    This is an integration check: even if main.py passes provider= to the cache
    module, the cache module must honor it. We test that the cache key for the
    same query differs when provider differs.
    """
    # Compute cache keys for two providers
    key_kimi = cache_mod.cache_key("transformer", 1, 0.5, provider="kimi")
    key_glm = cache_mod.cache_key("transformer", 1, 0.5, provider="glm")
    assert key_kimi != key_glm, (
        "cache_key must differ across providers (cache module regression?). "
        f"kimi={key_kimi}, glm={key_glm}"
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
