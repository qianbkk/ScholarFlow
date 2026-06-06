"""Tests for CRITICAL-002 + PERF-002: /search budget return in try/finally.

Background
----------
The /search endpoint previously did NOT guarantee budget return on the
exception path. The current architecture has a try/except that handles
`asyncio.TimeoutError` and `Exception`, returning budget before raising
HTTPException. These tests verify that budget is returned even when
the underlying `search_graph.ainvoke` raises any exception type.

Test strategy
-------------
1. Mock `search_graph.ainvoke` to raise various exception types.
2. Mock `_return_budget` to track invocations.
3. Assert that `_return_budget` was called with `req.budget` (the reserved
   amount) before the HTTP error was raised.
4. Cover RuntimeError, ValueError, KeyError, generic Exception, and a
   custom exception class to ensure the try/finally-like behavior holds.
"""
import time as _time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod
from backend.utils import cache as cache_mod


# ===== Fixtures =====

@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Reset budget state and isolate cache DB per test."""
    db_path = tmp_path / "test_budget_try_finally.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 50.0)
    # Reset slowapi rate limiter (otherwise tests after 5 hit 429).
    try:
        main_mod.limiter.reset()
    except Exception:
        pass
    yield


@pytest.fixture
def client():
    return TestClient(main_mod.app)


def _seed_budget(total: float) -> None:
    """Put the budget pool at `total` USD before the test request."""
    main_mod._save_budget_to_db(total, _time.time())


def _make_failing_graph(exc: BaseException):
    """Return a fake `ainvoke` that raises the given exception."""

    async def fake_ainvoke(initial):
        raise exc

    return fake_ainvoke


def _mock_provider_list(monkeypatch, providers=("kimi",)):
    """Make _resolve_provider accept the given provider ids."""
    monkeypatch.setattr(
        main_mod,
        "_get_providers_with_keys",
        lambda: [{"id": pid, "has_key": True} for pid in providers],
    )


# ===== 1) RuntimeError during pipeline → budget returned =====

def test_budget_returned_on_runtime_error(client, monkeypatch):
    """search_graph.ainvoke raises RuntimeError → _return_budget called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)  # fresh budget

    # Capture _return_budget calls
    return_calls = []

    async def fake_return_budget(amount):
        return_calls.append(amount)
        # Use real implementation to update DB? No — just track.
        return None

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)

    # Make pipeline raise RuntimeError
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(RuntimeError("simulated pipeline failure")),
    )

    # Cache miss → forces pipeline run
    async def fake_get_cached(*args, **kwargs):
        return None

    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "transformer", "max_iterations": 1, "budget": 0.5},
    )

    # Server returns 500 (the exception is caught and re-raised as HTTPException)
    assert resp.status_code == 500, f"expected 500, got {resp.status_code}: {resp.text}"

    # CRITICAL ASSERTION: _return_budget was called.
    assert len(return_calls) >= 1, (
        f"CRITICAL-002 FAIL: _return_budget not called when pipeline raised RuntimeError. "
        f"Calls: {return_calls}. Budget is leaked (50% reserved) — subsequent requests "
        "will be incorrectly rejected with 503."
    )
    # Returned amount should match the reserved budget (full return, since actual cost is unknown).
    assert any(c >= 0.5 - 1e-6 for c in return_calls), (
        f"_return_budget should be called with req.budget (0.5) on exception. "
        f"Calls: {return_calls}"
    )


# ===== 2) ValueError during pipeline → budget returned =====

def test_budget_returned_on_value_error(client, monkeypatch):
    """search_graph.ainvoke raises ValueError → _return_budget called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(ValueError("invalid state")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "rosettafold", "max_iterations": 1, "budget": 0.5},
    )

    assert resp.status_code == 500
    assert len(return_calls) >= 1, (
        "CRITICAL-002 FAIL: _return_budget not called on ValueError. "
        f"Calls: {return_calls}"
    )


# ===== 3) KeyError during pipeline → budget returned =====

def test_budget_returned_on_key_error(client, monkeypatch):
    """search_graph.ainvoke raises KeyError → _return_budget called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(KeyError("missing_field")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "BERT", "max_iterations": 1, "budget": 0.5},
    )

    assert resp.status_code == 500
    assert len(return_calls) >= 1, (
        f"CRITICAL-002 FAIL: _return_budget not called on KeyError. Calls: {return_calls}"
    )


# ===== 4) Generic Exception → budget returned =====

def test_budget_returned_on_generic_exception(client, monkeypatch):
    """search_graph.ainvoke raises generic Exception → _return_budget called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(Exception("generic failure")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "graph neural", "max_iterations": 1, "budget": 0.5},
    )

    assert resp.status_code == 500
    assert len(return_calls) >= 1, (
        f"CRITICAL-002 FAIL: _return_budget not called on generic Exception. "
        f"Calls: {return_calls}"
    )


# ===== 5) Custom exception class → budget returned =====

def test_budget_returned_on_custom_exception(client, monkeypatch):
    """A custom exception type → _return_budget still called (covers future exceptions)."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount):
        return_calls.append(amount)
        return None

    class CustomPipelineError(Exception):
        pass

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(CustomPipelineError("custom")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "diffusion", "max_iterations": 1, "budget": 0.5},
    )

    assert resp.status_code == 500
    assert len(return_calls) >= 1, (
        f"CRITICAL-002 FAIL: _return_budget not called on CustomPipelineError. "
        f"Calls: {return_calls}"
    )


# ===== 6) TimeoutError → budget returned (existing behavior, regression check) =====

def test_budget_returned_on_timeout(client, monkeypatch):
    """asyncio.TimeoutError (from ainvoke) → _return_budget called with full budget.

    This is the existing CRITICAL-002 + PERF-002 fix path. We test that the
    full budget is returned when the pipeline times out.
    """
    import asyncio
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)

    async def fake_ainvoke(initial):
        await asyncio.sleep(0)  # yield
        raise asyncio.TimeoutError("simulated 240s timeout")

    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "transformer", "max_iterations": 1, "budget": 0.5},
    )

    assert resp.status_code == 504, f"expected 504 timeout, got {resp.status_code}: {resp.text}"
    assert len(return_calls) >= 1, (
        f"CRITICAL-002 FAIL: _return_budget not called on TimeoutError. Calls: {return_calls}"
    )
    assert any(c >= 0.5 - 1e-6 for c in return_calls), (
        f"Timeout should return full budget (0.5). Calls: {return_calls}"
    )


# ===== 7) Success path → budget return reflects actual cost (regression) =====

def test_budget_return_on_success_returns_diff(client, monkeypatch):
    """On success, _return_budget is called with (req.budget - actual_cost),
    not the full budget. This confirms the happy path still works after
    the try/finally-like exception handling.
    """
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount):
        return_calls.append(amount)
        return None

    async def fake_ainvoke(initial):
        return {
            **initial,
            "report": "ok",
            "ranked_papers": [],
            "citation_graph": {"nodes": [], "links": []},
            "total_cost_usd": 0.1,  # actual cost
            "total_tokens_used": 100,
            "model_usage": {},
            "iteration": 0,
            "status": "done",
        }

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "transformer", "max_iterations": 1, "budget": 0.5},
    )

    assert resp.status_code == 200
    # diff = 0.5 - 0.1 = 0.4
    assert any(abs(c - 0.4) < 0.011 for c in return_calls), (
        f"On success, _return_budget should be called with diff (≈0.4). Calls: {return_calls}"
    )


# ===== 8) Defensive: source must have return-on-exception pattern =====

def test_main_py_handles_exception_in_search():
    """Source-level check: /search must handle generic Exception and call _return_budget."""
    from pathlib import Path
    src = Path(main_mod.__file__).read_text(encoding="utf-8")

    # The exception handler block must include a _return_budget call.
    import re
    # Look for the except Exception block in /search and verify it calls _return_budget
    # Use a greedy match until the next top-level `@app.` decorator.
    search_block = re.search(
        r"async def search\([^)]*\):.*?(?=\n@app\.)",
        src,
        flags=re.DOTALL,
    )
    if search_block is None:
        # Fallback: take everything from `async def search` to the next `def ` or `@`
        search_block = re.search(
            r"async def search\([^)]*\):.*?(?=\nasync def |\n@app\.|\ndef )",
            src,
            flags=re.DOTALL,
        )
    assert search_block is not None, "could not locate search() function in main.py"

    body = search_block.group(0)
    # Find except Exception block
    has_except_handler = "except Exception" in body
    assert has_except_handler, "search() must have an except Exception handler"

    # Within the except Exception block, _return_budget must be called.
    # Easiest: check that _return_budget is referenced in the function body at all
    # AND that the structure has an except Exception with return call.
    # We require at least one _return_budget in the function body (covers both
    # timeout and exception paths).
    assert "_return_budget" in body, (
        "CRITICAL-002 FAIL: /search function body must call _return_budget on the "
        "exception path so reserved budget is returned."
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
