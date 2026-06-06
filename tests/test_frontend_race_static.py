"""Static checks for H5 + H6 audit findings in `frontend/src/hooks/useSearch.ts`.

These are AST-light text checks (no JS/TS runtime needed) so they run
under the existing pytest suite without needing a live frontend /
backend. They are belt-and-suspenders — the manual Playwright test
under ``tests/manual/test_frontend_race.py`` exercises the real flow.

Invariants enforced:

  H5 (cross-close race):
    * ``myEs`` is declared as a local const inside ``searchWithSSE``
    * ``cleanup()`` references ``myEs`` (not the dynamic ``esRef.current``)
    * both ``onmessage`` and ``onerror`` guard with
      ``myEs !== esRef.current``
    * the old EventSource is closed at the start of a new search before
      a new one is constructed

  H6 (reset() + generation counter):
    * ``genRef`` is declared as a ``useRef<number>``
    * ``search()`` increments ``genRef.current`` before invoking SSE
    * ``reset()`` increments ``genRef.current``
    * ``reset()`` calls ``setLoading(false)``
    * both ``onmessage`` and ``onerror`` guard with
      ``myGen !== genRef.current``
    * the async fallback chain (searchPapers().then().catch().finally)
      also guards with ``myGen !== genRef.current``
"""
import re
from pathlib import Path

import pytest

USE_SEARCH_TS = (
    Path(__file__).resolve().parent.parent / "frontend" / "src" / "hooks" / "useSearch.ts"
)


@pytest.fixture(scope="module")
def source() -> str:
    assert USE_SEARCH_TS.exists(), f"useSearch.ts not found at {USE_SEARCH_TS}"
    return USE_SEARCH_TS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# H5: cross-close race
# ---------------------------------------------------------------------------

def test_h5_myEs_declared_as_local_const(source: str) -> None:
    """`myEs` must be declared as a const inside `searchWithSSE` so the
    cleanup/handler closures bind to this specific EventSource, not
    whatever `esRef.current` points to at teardown time."""
    assert "const myEs = es;" in source, (
        "H5 FAIL: `const myEs = es;` is missing — closures would otherwise "
        "read `esRef.current` dynamically and close the wrong connection."
    )


def test_h5_cleanup_uses_myEs_not_esRef(source: str) -> None:
    """`cleanup()` must close `myEs` (closure-bound) and only null out
    `esRef.current` when it still equals `myEs`."""
    # Find the cleanup function body
    m = re.search(
        r"const\s+cleanup\s*=\s*\(\)\s*=>\s*\{(.+?)\}\s*;",
        source,
        re.DOTALL,
    )
    assert m, "H5 FAIL: could not locate the cleanup() function body"
    body = m.group(1)
    # Must close myEs
    assert "myEs.close()" in body, (
        "H5 FAIL: cleanup() does not call `myEs.close()` — it must close "
        "the closure-bound `myEs`, not whatever esRef.current points to."
    )
    # Should also have a safety check before nulling esRef.current
    assert "esRef.current === myEs" in body, (
        "H5 FAIL: cleanup() should null esRef.current only when it still "
        "equals myEs (i.e. no newer EventSource has been assigned)."
    )


def test_h5_onmessage_guards_myEs(source: str) -> None:
    """onmessage must check `myEs !== esRef.current` to drop stale events."""
    m = re.search(
        r"es\.onmessage\s*=\s*\(ev\)\s*=>\s*\{(.+?)\}\s*;",
        source,
        re.DOTALL,
    )
    assert m, "H5 FAIL: could not locate es.onmessage body"
    body = m.group(1)
    assert "myEs !== esRef.current" in body, (
        "H5 FAIL: onmessage does not guard `myEs !== esRef.current` — "
        "stale events from a closed connection will still mutate state."
    )


def test_h5_onerror_guards_myEs(source: str) -> None:
    """onerror must check `myEs !== esRef.current` to drop stale errors."""
    m = re.search(
        r"es\.onerror\s*=\s*\(\)\s*=>\s*\{(.+?)\}\s*;",
        source,
        re.DOTALL,
    )
    assert m, "H5 FAIL: could not locate es.onerror body"
    body = m.group(1)
    assert "myEs !== esRef.current" in body, (
        "H5 FAIL: onerror does not guard `myEs !== esRef.current` — "
        "stale error events from a closed connection can still trigger "
        "fallback / setError / setLoading(false)."
    )


def test_h5_old_es_closed_before_new_one(source: str) -> None:
    """At the start of `searchWithSSE`, the previous EventSource must be
    closed before a new one is created (avoid two ESs briefly coexisting)."""
    m = re.search(
        r"const\s+searchWithSSE\s*=\s*useCallback\(\s*\([^)]*\)\s*=>\s*\{(.+?)\}\s*,\s*\[",
        source,
        re.DOTALL,
    )
    assert m, "H5 FAIL: could not locate searchWithSSE body"
    body = m.group(1)
    # The first `esRef.current` reference in the body should be a close()
    first_esRef_block = re.search(
        r"if\s*\(\s*esRef\.current\s*\)\s*\{[^}]*?esRef\.current\.close\(\)",
        body,
    )
    assert first_esRef_block, (
        "H5 FAIL: searchWithSSE does not close the previous EventSource "
        "before constructing a new one — `esRef.current.close()` should "
        "be invoked at the start of the function."
    )


# ---------------------------------------------------------------------------
# H6: reset() + generation counter
# ---------------------------------------------------------------------------

def test_h6_genRef_declared(source: str) -> None:
    """`genRef` must be a `useRef<number>` for the generation counter."""
    assert re.search(r"const\s+genRef\s*=\s*useRef<number>\(\d+\)", source), (
        "H6 FAIL: `genRef = useRef<number>(0)` is missing — needed so "
        "late events from a previous (cancelled) search can be detected."
    )


def test_h6_myGen_declared_as_local_const(source: str) -> None:
    """`myGen` must be captured per-call inside searchWithSSE."""
    assert "const myGen = genRef.current;" in source, (
        "H6 FAIL: `const myGen = genRef.current;` is missing — handlers "
        "would not know which generation they belong to."
    )


def test_h6_search_bumps_generation(source: str) -> None:
    """`search()` must increment `genRef.current` before kicking off SSE."""
    m = re.search(
        r"const\s+search\s*=\s*useCallback\(\s*async\s*\([^)]*\)\s*=>\s*\{(.+?)\}\s*,\s*\[",
        source,
        re.DOTALL,
    )
    assert m, "H6 FAIL: could not locate search() body"
    body = m.group(1)
    assert "genRef.current += 1" in body, (
        "H6 FAIL: `search()` does not bump `genRef.current` — a new search "
        "would not invalidate in-flight stale events from the previous one."
    )


def test_h6_reset_bumps_generation_and_clears_loading(source: str) -> None:
    """`reset()` must bump `genRef.current` AND call `setLoading(false)`."""
    m = re.search(
        r"const\s+reset\s*=\s*useCallback\(\s*\(\)\s*=>\s*\{(.+?)\}\s*,\s*\[\s*\]\s*\)",
        source,
        re.DOTALL,
    )
    assert m, "H6 FAIL: could not locate reset() body"
    body = m.group(1)
    assert "genRef.current += 1" in body, (
        "H6 FAIL: `reset()` does not bump `genRef.current` — in-flight "
        "fallback .then() from a cancelled search would still resolve and "
        "overwrite state."
    )
    assert "setLoading(false)" in body, (
        "H6 FAIL: `reset()` does not call `setLoading(false)` — submit "
        "button stays disabled and CostDashboard keeps pulsing after a "
        "mid-flight reset."
    )


def test_h6_onmessage_guards_myGen(source: str) -> None:
    """onmessage must check `myGen !== genRef.current` to drop stale events."""
    m = re.search(
        r"es\.onmessage\s*=\s*\(ev\)\s*=>\s*\{(.+?)\}\s*;",
        source,
        re.DOTALL,
    )
    assert m, "H6 FAIL: could not locate es.onmessage body"
    body = m.group(1)
    assert "myGen !== genRef.current" in body, (
        "H6 FAIL: onmessage does not guard `myGen !== genRef.current` — "
        "stale events from a reset/cancelled search will still mutate state."
    )


def test_h6_onerror_guards_myGen(source: str) -> None:
    """onerror must check `myGen !== genRef.current` to drop stale errors."""
    m = re.search(
        r"es\.onerror\s*=\s*\(\)\s*=>\s*\{(.+?)\}\s*;",
        source,
        re.DOTALL,
    )
    assert m, "H6 FAIL: could not locate es.onerror body"
    body = m.group(1)
    assert "myGen !== genRef.current" in body, (
        "H6 FAIL: onerror does not guard `myGen !== genRef.current` — "
        "stale error events from a reset/cancelled search will still "
        "trigger fallback / setError / setLoading(false)."
    )


def test_h6_fallback_chain_guards_myGen(source: str) -> None:
    """The async fallback chain (searchPapers().then().catch().finally)
    must guard each branch with `myGen !== genRef.current` so a late
    resolve from a cancelled search does not re-set state."""
    # Locate the fallback block (the one inside the `!receivedAnyEvent`
    # branch of onerror, NOT the `try { new EventSource } catch` early return).
    # It is the one that contains both `searchPapers(query, budget, maxIter, ...)`
    # AND `myGen !== genRef.current`.
    # provider 是 4th 可选参数 — 用 `[^;]*?` 兼容 `searchPapers(query, budget, maxIter)` 和
    # `searchPapers(query, budget, maxIter, provider)` 两种形态。
    matches = re.findall(
        r"searchPapers\(query, budget, maxIter[^)]*\)[\s\S]+?\.finally\(\(\)\s*=>\s*\{[\s\S]+?\}\s*\)\s*;",
        source,
    )
    assert matches, "H6 FAIL: could not locate searchPapers fallback chain"
    # Use the LAST match (the !receivedAnyEvent branch is the bigger one;
    # the early-return one is a single .then().catch().finally() shorter).
    body = matches[-1]
    # Should appear 3 times: .then, .catch, .finally
    occurrences = body.count("myGen !== genRef.current")
    assert occurrences >= 3, (
        f"H6 FAIL: expected `myGen !== genRef.current` to appear in .then(), "
        f".catch() and .finally() of the fallback chain (>=3 times), "
        f"found {occurrences}."
    )
