"""Cache provider dimension & init flag (B-group) — merged test suite.

merged from test_cache_key_provider.py, test_cache_key_provider_passed.py,
test_cache_provider_and_init_flag.py on 2026-06-07.

Sections:
  1) cache_key dimensions (key_provider + provider_and_init_flag)
  2) main.py must pass provider= to cache (key_provider_passed)
  3) _init_db_once flag (provider_and_init_flag)
  4) end-to-end round trip with provider (provider_and_init_flag)
  5) async round trip (provider_and_init_flag)
"""
import asyncio
import inspect
import sqlite3
import time as _time
from unittest.mock import AsyncMock

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
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    monkeypatch.setattr(main_mod, "GLOBAL_HOURLY_BUDGET", 50.0)
    yield


@pytest.fixture
def temp_cache_db(monkeypatch, tmp_path):
    """隔离 cache DB 到 temp 文件，避免污染真实数据。"""
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir(exist_ok=True)
    db_path = cache_dir / "test_search_cache.sqlite"
    monkeypatch.setattr(cache_mod, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    return db_path


@pytest.fixture
def fake_search_graph(monkeypatch):
    """Mock search_graph.ainvoke to return a minimal valid final state."""
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
    return TestClient(main_mod.app)


# ============================================================
# 1) cache_key 维度 (key_provider + provider_and_init_flag)
# ============================================================

def test_cache_key_differs_by_provider():
    """不同 LLM provider 应生成不同 cache key（核心：避免跨 provider 污染）。"""
    k_kimi = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    k_minimax = cache_mod.cache_key("q", 3, 1.0, provider="minimax")
    k_glm = cache_mod.cache_key("q", 3, 1.0, provider="glm")
    k_anthropic = cache_mod.cache_key("q", 3, 1.0, provider="anthropic")
    keys = [k_kimi, k_minimax, k_glm, k_anthropic]
    assert len(set(keys)) == 4, (
        f"4 个不同 provider 应生成 4 个不同 key, 实际 {len(set(keys))} 个 unique: {keys}"
    )


def test_cache_key_default_provider_is_deterministic():
    """无 provider (None) 时, 同 query + 同参数 → 同 key（向后兼容, 稳定）。"""
    k1 = cache_mod.cache_key("q", 3, 1.0)  # provider=None
    k2 = cache_mod.cache_key("q", 3, 1.0, provider=None)
    k3 = cache_mod.cache_key("q", 3, 1.0)
    assert k1 == k2 == k3


def test_cache_key_default_differs_from_specific_provider():
    """默认 (None) provider 的 key 应与具体 provider 的 key 不同。"""
    k_default = cache_mod.cache_key("q", 3, 1.0)
    k_kimi = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    assert k_default != k_kimi


def test_cache_key_same_provider_same_inputs_same_key():
    """同 provider + 同其他参数 → 相同 key（hash 稳定性）。"""
    k1 = cache_mod.cache_key("transformer", 3, 1.0, provider="kimi")
    k2 = cache_mod.cache_key("transformer", 3, 1.0, provider="kimi")
    assert k1 == k2


def test_cache_key_signature_accepts_provider():
    """cache_key 签名应包含 provider 参数（默认 None, 向后兼容）。"""
    sig = inspect.signature(cache_mod.cache_key)
    assert "provider" in sig.parameters
    assert sig.parameters["provider"].default is None


def test_cache_key_provider_is_case_sensitive():
    """provider 大小写敏感 (与 config.get_provider_config 一致)。"""
    k_lower = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    k_upper = cache_mod.cache_key("q", 3, 1.0, provider="KIMI")
    assert k_lower != k_upper


def test_cache_key_provider_none_default():
    """[from provider_and_init_flag] provider=None 与 provider='default' 应等价。"""
    k_none = cache_mod.cache_key("q", 3, 1.0, provider=None)
    k_default = cache_mod.cache_key("q", 3, 1.0, provider="default")
    assert k_none == k_default, "provider=None 应等同于 provider='default'"


def test_cache_key_provider_distinguishes_identical_query():
    """[from provider_and_init_flag] 同 query 在不同 provider 下 key 不同（防跨 provider 污染）。"""
    k_kimi = cache_mod.cache_key("transformer attention", 3, 1.0, provider="kimi")
    k_glm = cache_mod.cache_key("transformer attention", 3, 1.0, provider="glm")
    assert k_kimi != k_glm


def test_cache_key_provider_backward_compat():
    """[from provider_and_init_flag] 不传 provider（位置参数兼容旧调用）也能正常工作。"""
    k = cache_mod.cache_key("q", 3, 1.0)
    k_explicit = cache_mod.cache_key("q", 3, 1.0, provider=None)
    assert k == k_explicit


def test_cache_key_provider_changes_value_not_other_dimensions():
    """[from provider_and_init_flag] 只有 provider 维度变化时 key 变化；其他维度不变时 key 稳定。"""
    k1 = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    k2 = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    assert k1 == k2


# ============================================================
# 2) main.py /search & /search/stream must pass provider= (key_provider_passed)
# ============================================================

def test_search_passes_provider_to_get_cached(client, fake_search_graph, monkeypatch):
    """/search must call get_cached_async with provider=provider kwarg."""
    captured = {}

    async def fake_get_cached(query, max_iterations, budget, ttl_seconds=None, provider=None):
        captured["query"] = query
        captured["max_iterations"] = max_iterations
        captured["budget"] = budget
        captured["provider"] = provider
        return None  # cache miss — force pipeline run

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    resp = client.post(
        "/search",
        json={"query": "transformer attention", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 200, f"/search should succeed, got {resp.status_code}: {resp.text}"

    assert "provider" in captured, (
        "CRITICAL-001 FAIL: get_cached_async was called without provider= kwarg. "
        "main.py /search must pass provider=provider so cache key is provider-scoped."
    )
    assert captured["provider"] is not None
    assert isinstance(captured["provider"], str)


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

    async def fake_get_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "set_cached_async", fake_set_cached)
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    resp = client.post(
        "/search",
        json={"query": "graph neural networks", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 200, f"/search failed: {resp.status_code} {resp.text}"

    assert "provider" in captured, (
        "CRITICAL-001 FAIL: set_cached_async was called without provider= kwarg."
    )
    assert captured["provider"] is not None


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

    assert captured.get("provider") == "glm", (
        f"Provider should be 'glm' (user-supplied), got {captured.get('provider')!r}. "
        "main.py /search must resolve user provider and pass it to cache calls."
    )


def test_stream_passes_provider_to_get_cached(client, fake_search_graph, monkeypatch):
    """/search/stream must also call get_cached_async with provider= kwarg."""
    captured = {}

    async def fake_get_cached(query, max_iterations, budget, ttl_seconds=None, provider=None):
        captured["query"] = query
        captured["provider"] = provider
        return None

    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    async def fake_astream(*args, **kwargs):
        return
        yield  # Make it a generator (never reached)

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

    monkeypatch.setattr(
        main_mod,
        "_get_providers_with_keys",
        lambda: [{"id": "kimi", "has_key": True}],
    )

    with client.stream(
        "GET",
        "/search/stream",
        params={"q": "transformer", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
    ) as resp:
        try:
            for _ in resp.iter_lines():
                break
        except Exception:
            pass

    assert "provider" in captured, (
        "CRITICAL-001 FAIL: /search/stream called get_cached_async without provider= kwarg"
    )
    assert captured["provider"] == "kimi"


def test_search_get_cached_call_args_kwarg_present(client, fake_search_graph, monkeypatch):
    """Inspect mock.call_args.kwargs to assert provider= was passed by name."""
    mock_get = AsyncMock(return_value=None)
    mock_set = AsyncMock()

    monkeypatch.setattr(main_mod, "get_cached_async", mock_get)
    monkeypatch.setattr(main_mod, "set_cached_async", mock_set)

    resp = client.post(
        "/search",
        json={"query": "rosettafold", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 200, f"/search failed: {resp.status_code} {resp.text}"

    assert mock_get.await_count >= 1, "get_cached_async was not awaited"
    call = mock_get.call_args
    assert call is not None, "get_cached_async has no recorded call"

    kwargs = call.kwargs if hasattr(call, "kwargs") else {}
    assert "provider" in kwargs, (
        f"CRITICAL-001 FAIL: get_cached_async was not called with provider= keyword. "
        f"call.args={call.args!r}, call.kwargs={kwargs!r}"
    )
    assert kwargs["provider"] is not None

    assert mock_set.await_count >= 1, "set_cached_async was not awaited"
    set_call = mock_set.call_args
    set_kwargs = set_call.kwargs if hasattr(set_call, "kwargs") else {}
    assert "provider" in set_kwargs, (
        f"CRITICAL-001 FAIL: set_cached_async was not called with provider= keyword. "
        f"call.args={set_call.args!r}, call.kwargs={set_kwargs!r}"
    )
    assert set_kwargs["provider"] is not None


def test_main_py_source_passes_provider_to_cache():
    """Static fallback: main.py's /search and /search/stream should pass
    `provider=` to get_cached_async and set_cached_async call sites.
    """
    from pathlib import Path
    src_path = Path(main_mod.__file__)
    src = src_path.read_text(encoding="utf-8")

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
        "CRITICAL-001 FAIL: main.py must call get_cached_async with provider= kwarg."
    )
    assert has_provider_in_set, (
        "CRITICAL-001 FAIL: main.py must call set_cached_async with provider= kwarg."
    )


def test_search_different_providers_use_different_cache_keys(
    client, fake_search_graph, monkeypatch
):
    """Two requests with different provider= should compute different cache keys."""
    key_kimi = cache_mod.cache_key("transformer", 1, 0.5, provider="kimi")
    key_glm = cache_mod.cache_key("transformer", 1, 0.5, provider="glm")
    assert key_kimi != key_glm, (
        "cache_key must differ across providers (cache module regression?). "
        f"kimi={key_kimi}, glm={key_glm}"
    )


# ============================================================
# 3) _init_db_once 标志位 (provider_and_init_flag)
# ============================================================

def test_init_db_once_runs_only_first_time(temp_cache_db, monkeypatch):
    """_init_db_once 第二次调用时 _init_db 不会再被触发。"""
    call_count = [0]
    original_init_db = cache_mod._init_db

    def counting_init_db():
        call_count[0] += 1
        return original_init_db()

    monkeypatch.setattr(cache_mod, "_init_db", counting_init_db)
    assert cache_mod._DB_INITIALIZED is False

    cache_mod._init_db_once()
    assert call_count[0] == 1
    assert cache_mod._DB_INITIALIZED is True

    cache_mod._init_db_once()
    cache_mod._init_db_once()
    cache_mod._init_db_once()
    assert call_count[0] == 1, f"_init_db 被重复调用 {call_count[0]} 次（应有 1 次）"
    assert cache_mod._DB_INITIALIZED is True


def test_init_db_once_actually_creates_table(temp_cache_db):
    """首次 _init_db_once 必须真正创建 search_cache 表。"""
    assert cache_mod._DB_INITIALIZED is False
    cache_mod._init_db_once()

    conn = sqlite3.connect(str(temp_cache_db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_cache'"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, "search_cache 表未创建"


def test_get_cached_uses_init_db_once(temp_cache_db, monkeypatch):
    """get_cached 必须走 _init_db_once（不再每次调 _init_db）。"""
    call_count = [0]
    original = cache_mod._init_db

    def counting():
        call_count[0] += 1
        return original()

    monkeypatch.setattr(cache_mod, "_init_db", counting)

    cache_mod.get_cached("q", 3, 1.0)
    cache_mod.get_cached("q", 3, 1.0)
    cache_mod.get_cached("q", 3, 1.0)
    assert call_count[0] == 1, f"_init_db 被调用 {call_count[0]} 次（应仅 1 次）"


def test_set_cached_uses_init_db_once(temp_cache_db, monkeypatch):
    """set_cached 必须走 _init_db_once。"""
    call_count = [0]
    original = cache_mod._init_db

    def counting():
        call_count[0] += 1
        return original()

    monkeypatch.setattr(cache_mod, "_init_db", counting)

    cache_mod.set_cached("q", 3, 1.0, {"k": "v"}, 0.01, 10)
    cache_mod.set_cached("q", 3, 1.0, {"k": "v"}, 0.01, 10)
    assert call_count[0] == 1


# ============================================================
# 4) provider 端到端 (sync)
# ============================================================

def test_round_trip_with_provider(temp_cache_db):
    """带 provider 的 set_cached / get_cached round-trip。"""
    response = {"report": "## result", "ranked_papers": []}
    cache_mod.set_cached("transformer", 3, 1.0, response, 0.5, 100, provider="kimi")
    result = cache_mod.get_cached("transformer", 3, 1.0, provider="kimi")
    assert result is not None
    assert result[0] == response


def test_provider_isolation_no_cross_hit(temp_cache_db):
    """同 query 不同 provider 不应互相命中缓存。"""
    response_kimi = {"report": "kimi result", "ranked_papers": []}
    response_glm = {"report": "glm result", "ranked_papers": []}

    cache_mod.set_cached("q", 3, 1.0, response_kimi, 0.1, 10, provider="kimi")
    cache_mod.set_cached("q", 3, 1.0, response_glm, 0.1, 10, provider="glm")

    got_kimi = cache_mod.get_cached("q", 3, 1.0, provider="kimi")
    assert got_kimi is not None
    assert got_kimi[0] == response_kimi

    got_glm = cache_mod.get_cached("q", 3, 1.0, provider="glm")
    assert got_glm is not None
    assert got_glm[0] == response_glm

    assert got_kimi[0] != got_glm[0]


def test_provider_none_does_not_hit_provider_specific(temp_cache_db):
    """provider=None 应与 provider="kimi" 视为不同 key（避免污染）。"""
    response = {"report": "kimi", "ranked_papers": []}
    cache_mod.set_cached("q", 3, 1.0, response, 0.1, 10, provider="kimi")

    got = cache_mod.get_cached("q", 3, 1.0, provider=None)
    assert got is None


# ============================================================
# 5) provider 端到端 (async)
# ============================================================

@pytest.mark.asyncio
async def test_async_round_trip_with_provider(temp_cache_db):
    """async 变体也支持 provider 参数。"""
    response = {"report": "async kimi", "ranked_papers": []}
    await cache_mod.set_cached_async(
        "q", 3, 1.0, response, 0.1, 10, provider="kimi",
    )
    got = await cache_mod.get_cached_async("q", 3, 1.0, provider="kimi")
    assert got is not None
    assert got[0] == response


@pytest.mark.asyncio
async def test_async_provider_isolation(temp_cache_db):
    """async 变体也应跨 provider 隔离。"""
    r1 = {"report": "r1"}
    r2 = {"report": "r2"}
    await cache_mod.set_cached_async("q", 3, 1.0, r1, 0.1, 10, provider="kimi")
    await cache_mod.set_cached_async("q", 3, 1.0, r2, 0.1, 10, provider="glm")

    got1 = await cache_mod.get_cached_async("q", 3, 1.0, provider="kimi")
    got2 = await cache_mod.get_cached_async("q", 3, 1.0, provider="glm")
    assert got1[0] == r1
    assert got2[0] == r2


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
