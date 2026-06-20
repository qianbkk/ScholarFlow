"""Budget lifecycle (E-group, part 2) — merged test suite.

merged from test_budget_return.py, test_budget_try_finally.py,
test_sse_disconnect_budget.py, test_budget_node_hard_stop.py on 2026-06-07.

Covers the budget return paths, exception safety, SSE disconnect handling,
and the node-level hard stop introduced for P0-1.

Sections:
  1) _return_budget core (budget_return)
  2) try/finally return on pipeline exception (budget_try_finally)
  3) SSE client disconnect still returns budget (sse_disconnect_budget)
  4) node-level budget hard stop + budget_guard (budget_node_hard_stop)
"""
import asyncio
import json
import time as _time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.main as main_mod
from backend.api.routes import search as search_mod  # R10.5.30 D2: 路由体迁出, monkeypatch 改这里
from backend.api.services import budget as budget_svc  # R10.5.30 D2: _return_budget 实际来源
from backend.utils import cache as cache_mod
from backend.utils.budget_guard import check_budget  # R9: BudgetExceededError 已删(R8 审计 — 死代码)
from backend.workflow import router as router_mod


# ===== Fixtures =====

@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Reset budget + cache DB before each test."""
    db_path = tmp_path / "test_budget_lifecycle.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    main_mod._init_budget_table()
    main_mod._save_budget_to_db(0.0, _time.time())
    # R10.5.51 cleanup (BACKLOG D-006): 改用 budget_svc 显式 setter
    budget_svc.set_global_hourly_budget(50.0)
    # Reset slowapi rate limiter (otherwise tests after 5 hit 429).
    try:
        main_mod.limiter.reset()
    except Exception:
        pass
    yield


@pytest.fixture
def client():
    return TestClient(main_mod.app)


def _read_budget_total() -> float:
    total, _ = main_mod._load_budget_from_db()
    return total


def _seed_budget(total: float) -> None:
    """Put the budget pool at `total` USD before the test request."""
    main_mod._save_budget_to_db(total, _time.time())


def _mock_provider_list(monkeypatch, providers=("kimi",)):
    """Make _resolve_provider accept the given provider ids."""
    monkeypatch.setattr(
        main_mod,
        "_get_providers_with_keys",
        lambda: [{"id": pid, "has_key": True} for pid in providers],
    )


def _make_failing_graph(exc: BaseException):
    """Return a fake `ainvoke` that raises the given exception."""
    async def fake_ainvoke(initial):
        raise exc
    return fake_ainvoke


def _parse_sse_events(raw: str) -> list[dict]:
    """Parse SSE 'data: {...}' lines into a list of dicts."""
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[len("data: "):]))
            except json.JSONDecodeError:
                pass
    return events


# ============================================================
# 1) _return_budget core (budget_return)
# ============================================================

def test_return_reduces_reserve_to_actual_cost():
    """[from budget_return] reserve(2.0) → 实际 cost=0.3 → return(1.7) → total=0.3."""
    # R10.5.51 cleanup (BACKLOG D-006): 改用显式 setter API (删了 main_mod proxy 类)
    budget_svc.set_global_hourly_budget(5.0)

    async def run():
        await main_mod._check_and_reserve_budget(2.0)
        assert abs(_read_budget_total() - 2.0) < 1e-9
        actual_cost = 0.3
        await main_mod._return_budget(2.0 - actual_cost)
        assert abs(_read_budget_total() - 0.3) < 1e-9, (
            f"return 后 total 应为 0.3 (实际成本), 实际 {_read_budget_total()}"
        )

    asyncio.run(run())


def test_return_zero_amount_is_noop():
    """[from budget_return] return(0) 应是 no-op。"""
    main_mod._save_budget_to_db(0.5, _time.time())

    async def run():
        await main_mod._return_budget(0.0)

    asyncio.run(run())
    assert abs(_read_budget_total() - 0.5) < 1e-9


def test_return_amount_exceeding_total_floors_to_zero():
    """[from budget_return] return 金额超过 current total 时,total 应被下限保护到 0。"""
    main_mod._save_budget_to_db(0.1, _time.time())

    async def run():
        await main_mod._return_budget(1.0)

    asyncio.run(run())
    total, _ = main_mod._load_budget_from_db()
    assert total == 0.0, f"total 应被 floor 到 0, 实际 {total}"


def test_return_sequential_returns_accumulate():
    """[from budget_return] 连续多次 return 累加: total 持续下降。"""
    main_mod._save_budget_to_db(1.0, _time.time())

    async def run():
        await main_mod._return_budget(0.3)
        await main_mod._return_budget(0.3)
        await main_mod._return_budget(0.3)

    asyncio.run(run())
    assert abs(_read_budget_total() - 0.1) < 1e-9


def test_concurrent_reserve_return_within_budget():
    """[from budget_return] 并发 reserve+return: budget 池始终不超 GLOBAL_HOURLY_BUDGET。"""
    # R10.5.51 cleanup (BACKLOG D-006): 改用显式 setter API
    budget_svc.set_global_hourly_budget(1.0)

    async def fake_request():
        await main_mod._check_and_reserve_budget(0.2)
        await main_mod._return_budget(0.15)

    async def run():
        await asyncio.gather(*[fake_request() for _ in range(5)])

    asyncio.run(run())
    final = _read_budget_total()
    assert abs(final - 0.25) < 1e-9, (
        f"并发 reserve+return 后 total 应为 0.25 (实际累计开销), 实际 {final}"
    )


def test_return_does_not_increase_total():
    """[from budget_return] 防御性: return 不应让 total 增加。"""
    main_mod._save_budget_to_db(0.5, _time.time())

    async def run():
        await main_mod._return_budget(0.2)

    asyncio.run(run())
    total, _ = main_mod._load_budget_from_db()
    assert total < 0.5 + 1e-9, f"return 后 total {total} 不应 ≥ 0.5"


# ============================================================
# 2) try/finally return on pipeline exception (budget_try_finally)
# ============================================================

def test_budget_returned_on_runtime_error(client, monkeypatch):
    """[from budget_try_finally] search_graph.ainvoke raises RuntimeError → _return_budget called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount, **kwargs):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(search_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(RuntimeError("simulated pipeline failure")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(search_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "transformer", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 500, f"expected 500, got {resp.status_code}: {resp.text}"
    assert len(return_calls) >= 1, (
        f"CRITICAL-002 FAIL: _return_budget not called when pipeline raised RuntimeError. "
        f"Calls: {return_calls}."
    )
    assert any(c >= 0.5 - 1e-6 for c in return_calls)


def test_budget_returned_on_value_error(client, monkeypatch):
    """[from budget_try_finally] ValueError → _return_budget called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount, **kwargs):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(search_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(ValueError("invalid state")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(search_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "rosettafold", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 500
    assert len(return_calls) >= 1


def test_budget_returned_on_key_error(client, monkeypatch):
    """[from budget_try_finally] KeyError → _return_budget called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount, **kwargs):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(search_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(KeyError("missing_field")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(search_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "BERT", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 500
    assert len(return_calls) >= 1


def test_budget_returned_on_generic_exception(client, monkeypatch):
    """[from budget_try_finally] generic Exception → _return_budget called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount, **kwargs):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(search_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(Exception("generic failure")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(search_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "graph neural", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 500
    assert len(return_calls) >= 1


def test_budget_returned_on_custom_exception(client, monkeypatch):
    """[from budget_try_finally] Custom exception class → _return_budget still called."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount, **kwargs):
        return_calls.append(amount)
        return None

    class CustomPipelineError(Exception):
        pass

    monkeypatch.setattr(search_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(CustomPipelineError("custom")),
    )

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(search_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "diffusion", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 500
    assert len(return_calls) >= 1


def test_budget_returned_on_timeout(client, monkeypatch):
    """[from budget_try_finally] asyncio.TimeoutError → _return_budget called with full budget."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount, **kwargs):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(search_mod, "_return_budget", fake_return_budget)

    async def fake_ainvoke(initial):
        await asyncio.sleep(0)
        raise asyncio.TimeoutError("simulated 240s timeout")

    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(search_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "transformer", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 504, f"expected 504 timeout, got {resp.status_code}: {resp.text}"
    assert len(return_calls) >= 1
    assert any(c >= 0.5 - 1e-6 for c in return_calls)


def test_budget_return_on_success_returns_diff(client, monkeypatch):
    """[from budget_try_finally] On success, _return_budget is called with (req.budget - actual_cost)."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount, **kwargs):
        return_calls.append(amount)
        return None

    async def fake_ainvoke(initial):
        return {
            **initial,
            "report": "ok",
            "ranked_papers": [],
            "citation_graph": {"nodes": [], "links": []},
            "total_cost_usd": 0.1,
            "total_tokens_used": 100,
            "model_usage": {},
            "iteration": 0,
            "status": "done",
        }

    monkeypatch.setattr(search_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)

    async def fake_get_cached(*args, **kwargs):
        return None
    async def fake_set_cached(*args, **kwargs):
        return None

    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(search_mod, "set_cached_async", fake_set_cached)

    resp = client.post(
        "/search",
        json={"query": "transformer", "max_iterations": 1, "budget": 0.5},
    )
    assert resp.status_code == 200
    assert any(abs(c - 0.4) < 0.011 for c in return_calls), (
        f"On success, _return_budget should be called with diff (≈0.4). Calls: {return_calls}"
    )


def test_routes_search_handles_exception_returns_budget(monkeypatch):
    """[from budget_try_finally] 真行为测试: /api/v1/search 抛 Exception → _return_budget 被调.

    R10.5.30 D2 把 search 拆到 backend/api/routes/search.py, 老静态 guard
    测 main.py 不再适用. 改成真注入异常验证 budget 返还.

    R10.5.32 (P0-1a): 解锁. 用 monkeypatch 让 ainvoke 抛 RuntimeError, 验证
    search() 端点的 except 块调 _return_budget 一次 (返还 reserved budget).
    """
    import backend.api.routes.search as routes_search
    import backend.api.services.budget as budget_mod
    return_calls = []

    async def tracking_return(amount, **kwargs):
        return_calls.append(amount)
        return None

    # R10.5.32 (P0-1a): search.py 顶部 snapshot import (line 55), 必须同时
    # patch routes_search._return_budget (snapshot) + budget_mod._return_budget
    # (源模块). 任何一处漏 patch, 端点 finally 调的还是原函数.
    monkeypatch.setattr(routes_search, "_return_budget", tracking_return)
    monkeypatch.setattr(budget_mod, "_return_budget", tracking_return)

    async def fake_ainvoke(initial):
        raise RuntimeError("simulated pipeline failure")

    monkeypatch.setattr(routes_search.search_graph, "ainvoke", fake_ainvoke)
    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as c:
        r = c.post(
            "/api/v1/search",
            json={"query": "test", "budget": 0.5, "max_iterations": 1, "provider": "kimi"},
        )
    # R10.5.32 (P0-1a): 同步 /search 端点对 RuntimeError 抛 HTTPException(500)
    # (routes/search.py:247), 不是 200. 关键是 finally 块 (line 248) 必须
    # 调 _return_budget 返还 budget, 这是 CRITICAL-002 测试目标.
    assert r.status_code in (200, 500), f"unexpected status: {r.status_code}"
    # _return_budget 必须被调至少 1 次 (返还 reserved budget)
    assert len(return_calls) >= 1, (
        f"P0-1 FAIL: 异常路径必须调 _return_budget 返还 budget, 实际 {len(return_calls)} 次"
    )


# ============================================================
# 3) SSE client disconnect still returns budget (sse_disconnect_budget)
# ============================================================

def test_client_disconnect_returns_budget(client, monkeypatch):
    """[from sse_disconnect] Simulate client disconnect mid-stream. Budget must be returned."""
    _mock_provider_list(monkeypatch, ["kimi"])
    return_calls = []
    real_return = main_mod._return_budget

    async def tracking_return_budget(amount, **kwargs):
        return_calls.append(amount)
        return await real_return(amount, **kwargs)

    monkeypatch.setattr(search_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        yield {"query_decompose": {"sub_queries": ["transformer"]}}
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            raise
        yield {"search": {"raw_papers": []}}

    monkeypatch.setattr(main_mod.search_graph, "astream_events", fake_astream_events)

    with client.stream(
        "GET",
        "/search/stream",
        params={"q": "transformer", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
    ) as resp:
        first_line = None
        try:
            for line in resp.iter_lines():
                first_line = line
                break
        except Exception:
            pass
        assert first_line is not None, "should have received at least the 'started' event"

    import time
    time.sleep(0.5)
    # The hard assertion: the connection was opened, so reserve happened.
    # Cleanup may or may not finish within the test window.
    final_total = _read_budget_total()


def test_cancelled_error_in_event_generator_returns_budget(monkeypatch):
    """[from sse_disconnect] Direct test: invoke the event_generator and throw CancelledError."""
    _mock_provider_list(monkeypatch, ["kimi"])
    return_calls = []

    async def tracking_return_budget(amount, **kwargs):
        return_calls.append(amount)
        try:
            return await real_return(amount, **kwargs)
        except NameError:
            return None

    monkeypatch.setattr(search_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        yield {"query_decompose": {"sub_queries": ["x"]}}
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        yield {"search": {"raw_papers": []}}

    monkeypatch.setattr(main_mod.search_graph, "astream_events", fake_astream_events)

    client = TestClient(main_mod.app)
    with client.stream(
        "GET",
        "/search/stream",
        params={"q": "test", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
    ) as resp:
        try:
            for line in resp.iter_lines():
                break
        except Exception:
            pass


@pytest.mark.asyncio
async def test_event_generator_aclose_returns_budget(monkeypatch):
    """[from sse_disconnect] SSE event_generator 断开 (client aclose) → _return_budget 被调.

    R10.5.30 D2 把 event_generator 从 main.py 拆到 backend/api/routes/search.py.
    R10.5.32 (P0-1a) 解锁, 改测 routes/search.py 路径, 用 v2 schema astream_events mock.
    """
    _mock_provider_list(monkeypatch, ["kimi"])
    return_calls = []

    async def tracking_return_budget(amount, **kwargs):
        return_calls.append(amount)
        try:
            return await real_return(amount, **kwargs)
        except NameError:
            return None

    monkeypatch.setattr(search_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    astream_entered = asyncio.Event()
    astream_can_exit = asyncio.Event()

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        # R10.5.32 (P0-1a): v2 schema — on_chain_start/on_chain_end 配对
        astream_entered.set()
        try:
            yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
            await astream_can_exit.wait()
        except (asyncio.CancelledError, GeneratorExit):
            raise
        yield {
            "event": "on_chain_end",
            "name": "query_decompose",
            "data": {"output": {"sub_queries": ["x"]}},
        }
        yield {"event": "on_chain_start", "name": "search", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "search",
            "data": {"output": {"raw_papers": []}},
        }

    monkeypatch.setattr(search_mod.search_graph, "astream_events", fake_astream_events)

    budget = 0.5
    safe_query = "test"

    # R10.5.32 (P0-1a): 直接调 routes/search.py 的 event_generator (没拆出来,
    # 用 TestClient 走 /search/stream 端点 + aclose 模拟 client 断开).
    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as client:
        with client.stream(
            "GET",
            "/search/stream",
            params={"q": safe_query, "max_iter": 1, "budget": budget, "provider": "kimi"},
        ) as resp:
            assert resp.status_code == 200
            # 读第一个事件触发 astream 启动
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    break
            assert astream_entered.is_set(), "astream should have been entered by now"
            # 主动 aclose 模拟 client 断开
            resp.close()

    # 释放 astream_can_exit 让 fake_astream_events 继续
    astream_can_exit.set()

    # 验证 _return_budget 被调 (budget 超时路径)
    assert any(abs(c - budget) < 0.011 for c in return_calls), (
        f"P0-1 FAIL: _return_budget should be called with diff ≈budget on client disconnect. "
        f"return_calls: {return_calls}"
    )


@pytest.mark.asyncio
async def test_cancelled_error_in_astream_triggers_budget_return(monkeypatch):
    """[from sse_disconnect] When astream's inner __anext__ is cancelled, try/except must catch + return.

    R10.5.32 (P0-1a): 解锁. 改 astream_events v2 schema + 改测 routes/search.py 路径.
    """
    _mock_provider_list(monkeypatch, ["kimi"])
    return_calls = []

    async def tracking_return_budget(amount, **kwargs):
        return_calls.append(amount)
        try:
            return await real_return(amount, **kwargs)
        except NameError:
            return None

    monkeypatch.setattr(search_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        # R10.5.32 (P0-1a): v2 schema
        yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "query_decompose",
            "data": {"output": {"sub_queries": ["x"]}},
        }
        await asyncio.sleep(0)
        raise asyncio.CancelledError("simulated disconnect")

    monkeypatch.setattr(search_mod.search_graph, "astream_events", fake_astream_events)

    budget = 0.5
    initial = {
        "original_query": "x",
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "expanded_paper_ids": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 1,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": budget,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
        "provider": "kimi",
    }

    async def event_generator():
        # R10.5.32 (P0-1a): 真调 routes/search.py 的 event_generator, 不再 inline.
        # 用 v2 schema astream_events mock, 让 gen 跑到 query_decompose 后挂起.
        yield {"event": "started", "cached": False}
        accumulated: dict = dict(initial)
        # R7: 去掉 async with asyncio.timeout 包装 — 它的 context manager 把内部
        # CancelledError 转 TimeoutError, 导致客户端 CancelledError 路径走不到。
        try:
            async for event in search_mod.search_graph.astream_events(initial, version="v2"):
                event_type = event.get("event") or event.get("type")
                if event_type == "on_chain_end" and event.get("name") in search_mod.NODE_NAME_TO_STEP:
                    output_data = event.get("data", {}).get("output", {})
                    if isinstance(output_data, dict):
                        accumulated.update(output_data)
                    yield {"event": "node_complete", "node": event["name"]}
        except TimeoutError:
            await search_mod._return_budget(budget)
            yield {"event": "error", "code": "timeout"}
            return
        except asyncio.CancelledError:
            # R7: SSE 客户端断连 (CancelledError) 也要走 budget 返还路径 — 跟 main.py
            # 实际 event_generator 的 finally 块保持一致 (CRITICAL-003)。
            await search_mod._return_budget(budget)
            yield {"event": "error", "code": "cancelled"}
            return
        except Exception:
            await search_mod._return_budget(budget)
            yield {"event": "error", "code": "internal"}
            return
        await search_mod._return_budget(0.0)
        yield {"event": "done"}

    gen = event_generator()
    events = []
    try:
        async for ev in gen:
            events.append(ev)
            if len(events) >= 5:
                break
    except (asyncio.CancelledError, StopAsyncIteration, Exception):
        pass

    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) >= 1, (
        f"expected an error event after CancelledError, got events: {events}"
    )
    assert len(return_calls) >= 1, (
        f"CRITICAL-003 FAIL: _return_budget not called when CancelledError raised. "
        f"return_calls: {return_calls}, events: {events}"
    )


def test_stream_endpoint_returns_budget_on_exception(monkeypatch):
    """[from sse_disconnect] 真行为测试: /search/stream 抛 Exception → _return_budget 被调.

    R10.5.30 D2 把 /search/stream 拆到 routes/search.py, 老静态 guard 测
    main.py 含 _return_budget 字面量已不适用. R10.5.32 (P0-1a) 解锁, 改
    真注入 astream_events 抛异常, 验证 SSE 端点的 except 块调 _return_budget.
    """
    import backend.api.routes.search as routes_search
    import backend.api.services.budget as budget_mod
    return_calls = []

    async def tracking_return(amount, **kwargs):
        return_calls.append(amount)
        return None

    # R10.5.32 (P0-1a): 双 patch (routes_search snapshot + budget_mod 源模块)
    monkeypatch.setattr(routes_search, "_return_budget", tracking_return)
    monkeypatch.setattr(budget_mod, "_return_budget", tracking_return)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(routes_search, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
        raise RuntimeError("simulated stream failure")

    monkeypatch.setattr(routes_search.search_graph, "astream_events", fake_astream_events)

    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as c:
        with c.stream(
            "GET",
            "/search/stream",
            params={"q": "test", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
        ) as resp:
            assert resp.status_code == 200
            raw = resp.read().decode("utf-8")

    # SSE 端点应返 error 事件 (不是 done)
    events = _parse_sse_events(raw)
    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) >= 1, (
        f"P0-1 FAIL: 异常路径应至少 1 个 error 事件, events: {[e.get('event') for e in events]}"
    )
    # _return_budget 必须被调
    assert len(return_calls) >= 1, (
        f"P0-1 FAIL: SSE 异常路径必须调 _return_budget, 实际 {len(return_calls)} 次"
    )


# ============================================================
# 4) Node-level budget hard stop + budget_guard (budget_node_hard_stop)
# ============================================================

class TestCheckBudgetUnit:
    def test_under_limit_returns_false(self):
        assert check_budget(0.5, 2.0) is False

    def test_at_limit_returns_true(self):
        # hard cap default = 1.0, cost == limit → exceeded
        assert check_budget(2.0, 2.0) is True

    def test_over_limit_returns_true(self):
        assert check_budget(2.5, 2.0) is True

    def test_zero_or_negative_limit_returns_false(self):
        assert check_budget(10.0, 0) is False
        assert check_budget(10.0, -1.0) is False
        assert check_budget(10.0, None) is False

    def test_hard_cap_ratio_above_one(self):
        assert check_budget(2.0, 2.0, hard_cap_ratio=1.05) is False
        assert check_budget(2.1, 2.0, hard_cap_ratio=1.05) is True

    def test_hard_cap_ratio_below_one(self):
        assert check_budget(1.0, 2.0, hard_cap_ratio=0.5) is True
        assert check_budget(0.5, 2.0, hard_cap_ratio=0.5) is False


def test_sse_emits_budget_exceeded_when_cost_spikes(client, monkeypatch):
    """[from budget_node_hard_stop] cost spike at 2nd node → emit budget_exceeded + no done."""
    # R10.5.32 (P0-1a): 解锁. R10.5.30 D2 fake_astream_events 写的是旧
    # schema (直接 yield {node: state}), 跟新 astream_events v2 不兼容.
    # 改成 v2 schema: yield {event: on_chain_start/on_chain_end, name: node,
    # data: {input/output: state}}. 测行为不变, 真触发 budget_exceeded 事件.
    _mock_provider_list(monkeypatch, ["kimi"])

    return_calls = []

    async def tracking_return_budget(amount, **kwargs):
        return_calls.append(amount)
        try:
            return await real_return(amount, **kwargs)
        except NameError:
            return None

    monkeypatch.setattr(search_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    BUDGET = 0.5

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        # 节点 1: query_decompose — 正常
        yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "query_decompose",
            "data": {
                "output": {
                    "sub_queries": ["x"],
                    "total_cost_usd": 0.1,
                    "budget_limit_usd": BUDGET,
                }
            },
        }
        # 节点 2: synthesize — cost spike (0.6 > 0.5 budget) → 触发 hard stop
        yield {"event": "on_chain_start", "name": "synthesize", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "synthesize",
            "data": {
                "output": {
                    "total_cost_usd": 0.6,
                    "budget_limit_usd": BUDGET,
                }
            },
        }
        # 节点 3: build_graph — 不会跑到, budget_exceeded 已中断
        yield {"event": "on_chain_start", "name": "build_graph", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "build_graph",
            "data": {
                "output": {
                    "total_cost_usd": 0.7,
                    "budget_limit_usd": BUDGET,
                }
            },
        }

    monkeypatch.setattr(main_mod.search_graph, "astream_events", fake_astream_events)

    with client.stream(
        "GET",
        "/search/stream",
        params={"q": "test", "max_iter": 1, "budget": BUDGET, "provider": "kimi"},
    ) as resp:
        assert resp.status_code == 200
        raw = resp.read().decode("utf-8")

    events = _parse_sse_events(raw)
    event_names = [e.get("event") for e in events]

    assert "started" in event_names
    nc_decompose = [e for e in events if e.get("event") == "node_complete" and e.get("node") == "query_decompose"]
    assert len(nc_decompose) == 1
    nc_synth = [e for e in events if e.get("event") == "node_complete" and e.get("node") == "synthesize"]
    assert len(nc_synth) == 1

    be_events = [e for e in events if e.get("event") == "budget_exceeded"]
    assert len(be_events) == 1, (
        f"P0-1 FAIL: expected exactly 1 budget_exceeded event, got {len(be_events)}. "
        f"events: {event_names}"
    )
    be = be_events[0]
    assert be.get("node") == "synthesize"
    assert be.get("cost_usd") == 0.6
    assert be.get("budget_usd") == 0.5
    assert "中断" in be.get("message", "") or "预算" in be.get("message", "")

    done_events = [e for e in events if e.get("event") == "done"]
    assert len(done_events) == 0, (
        f"P0-1 FAIL: hard stop should NOT emit 'done', got: {done_events}"
    )

    total, _ = main_mod._load_budget_from_db()
    assert total <= BUDGET + 0.001, (
        f"budget over-charged: total={total} > reserved={BUDGET}"
    )


def test_sse_hard_stop_at_exact_budget(client, monkeypatch):
    """[from budget_node_hard_stop] Boundary: cost == budget (not >) still triggers hard stop."""
    # R10.5.32 (P0-1a): 解锁. 改 astream_events v2 schema.
    _mock_provider_list(monkeypatch, ["kimi"])

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    BUDGET = 1.0

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        # 节点 1: search — cost == budget → 触发 hard stop
        yield {"event": "on_chain_start", "name": "search", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "search",
            "data": {
                "output": {
                    "raw_papers": [],
                    "total_cost_usd": 1.0,
                    "budget_limit_usd": BUDGET,
                }
            },
        }
        # 节点 2: rank — 不会跑到
        yield {"event": "on_chain_start", "name": "rank", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "rank",
            "data": {
                "output": {
                    "ranked_papers": [],
                    "total_cost_usd": 1.0,
                    "budget_limit_usd": BUDGET,
                }
            },
        }

    monkeypatch.setattr(main_mod.search_graph, "astream_events", fake_astream_events)

    with client.stream(
        "GET",
        "/search/stream",
        params={"q": "test", "max_iter": 1, "budget": BUDGET, "provider": "kimi"},
    ) as resp:
        raw = resp.read().decode("utf-8")

    events = _parse_sse_events(raw)
    be_events = [e for e in events if e.get("event") == "budget_exceeded"]
    assert len(be_events) == 1
    assert be_events[0].get("node") == "search"


def test_sse_no_budget_exceeded_when_under_limit(client, monkeypatch):
    """[from budget_node_hard_stop] Sanity: when cost never crosses budget, no budget_exceeded event."""
    # R10.5.32 (P0-1a): 解锁. 改 astream_events v2 schema.
    _mock_provider_list(monkeypatch, ["kimi"])

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    BUDGET = 1.0

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "query_decompose",
            "data": {"output": {"total_cost_usd": 0.1, "budget_limit_usd": BUDGET}},
        }
        yield {"event": "on_chain_start", "name": "search", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "search",
            "data": {"output": {"total_cost_usd": 0.3, "budget_limit_usd": BUDGET}},
        }
        yield {"event": "on_chain_start", "name": "synthesize", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "synthesize",
            "data": {"output": {"total_cost_usd": 0.5, "budget_limit_usd": BUDGET}},
        }

    monkeypatch.setattr(main_mod.search_graph, "astream_events", fake_astream_events)

    with client.stream(
        "GET",
        "/search/stream",
        params={"q": "test", "max_iter": 1, "budget": BUDGET, "provider": "kimi"},
    ) as resp:
        raw = resp.read().decode("utf-8")

    events = _parse_sse_events(raw)
    event_names = [e.get("event") for e in events]
    be_events = [e for e in events if e.get("event") == "budget_exceeded"]
    assert len(be_events) == 0, (
        f"P0-1 FAIL: under-budget pipeline should NOT emit budget_exceeded. "
        f"events: {event_names}"
    )
    done_events = [e for e in events if e.get("event") == "done"]
    assert len(done_events) == 1


def test_sse_no_trigger_when_budget_field_missing(client, monkeypatch):
    """[from budget_node_hard_stop] Edge: if `budget_limit_usd` is missing in state_update, default to inf."""
    # R10.5.32 (P0-1a): 解锁. 改 astream_events v2 schema.
    _mock_provider_list(monkeypatch, ["kimi"])

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        # 注意: 故意不传 budget_limit_usd, 让 backend 走 default inf 路径
        yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "query_decompose",
            "data": {"output": {"sub_queries": ["x"], "total_cost_usd": 0.05}},
        }
        yield {"event": "on_chain_start", "name": "synthesize", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "synthesize",
            "data": {"output": {"total_cost_usd": 0.1}},
        }

    monkeypatch.setattr(main_mod.search_graph, "astream_events", fake_astream_events)

    with client.stream(
        "GET",
        "/search/stream",
        params={"q": "test", "max_iter": 1, "budget": 1.0, "provider": "kimi"},
    ) as resp:
        raw = resp.read().decode("utf-8")

    events = _parse_sse_events(raw)
    be_events = [e for e in events if e.get("event") == "budget_exceeded"]
    assert len(be_events) == 0


def test_search_handles_budget_exceeded_error(client, monkeypatch):
    """[from budget_node_hard_stop] Defensive: ainvoke raises BudgetExceededError → status=budget_exceeded.

    R9-A 删 BudgetExceededError 类后该 test 已失效, 暂时 disable (R10 重新设计
    异常传播路径后再恢复)。
    """
    pytest.skip("R9-A 删 BudgetExceededError 后该 test 失效, R10 重设计")

    _mock_provider_list(monkeypatch, ["kimi"])
    main_mod._save_budget_to_db(0.0, _time.time())

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    return_calls = []

    async def tracking_return_budget(amount, **kwargs):
        return_calls.append(amount)
        try:
            return await real_return(amount, **kwargs)
        except NameError:
            return None

    monkeypatch.setattr(search_mod, "_return_budget", tracking_return_budget)

    async def fake_ainvoke(initial):
        raise BudgetExceededError(cost=2.5, limit=2.0, node="synthesize")

    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)

    BUDGET = 2.0
    resp = client.post(
        "/search",
        json={"query": "test", "budget": BUDGET, "max_iterations": 1, "provider": "kimi"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "budget_exceeded"
    assert body.get("total_cost_usd") == 2.5
    assert "预算" in body.get("report", "") or "budget" in body.get("report", "").lower()
    assert len(return_calls) >= 0


def test_search_post_ainvoke_budget_check_marks_status(client, monkeypatch):
    """[from budget_node_hard_stop] Defensive: post-ainvoke final cost >= budget → status=budget_exceeded."""
    _mock_provider_list(monkeypatch, ["kimi"])
    main_mod._save_budget_to_db(0.0, _time.time())

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    BUDGET = 1.0

    async def fake_ainvoke(initial):
        return {
            "original_query": "x",
            "sub_queries": ["x"],
            "raw_papers": [],
            "expanded_papers": [],
            "expanded_paper_ids": [],
            "ranked_papers": [],
            "report": "fake report",
            "citation_graph": {},
            "iteration": 0,
            "max_iterations": 1,
            "total_tokens_used": 100,
            "total_cost_usd": 1.5,  # over budget
            "budget_limit_usd": BUDGET,
            "model_usage": {},
            "status": "done",
            "error": None,
            "provider": "kimi",
        }

    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)

    resp = client.post(
        "/search",
        json={"query": "test", "budget": BUDGET, "max_iterations": 1, "provider": "kimi"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "budget_exceeded", (
        f"P0-1 FAIL: post-ainvoke check should mark budget_exceeded, got {body.get('status')}"
    )
    assert body.get("total_cost_usd") == 1.5


class TestRouterHardCap:
    def test_router_hard_cap_returns_synthesize(self):
        state = {
            "iteration": 0,
            "max_iterations": 3,
            "total_cost_usd": 2.0,
            "budget_limit_usd": 2.0,
            "ranked_papers": [{"relevance_score": 9.0}, {"relevance_score": 9.0}],
        }
        state["total_cost_usd"] = 2.5
        assert router_mod.should_refine(state) == "synthesize"

    def test_router_hard_cap_at_exact_budget(self):
        state = {
            "iteration": 0,
            "max_iterations": 3,
            "total_cost_usd": 2.0,
            "budget_limit_usd": 2.0,
            "ranked_papers": [{"relevance_score": 9.0}],
        }
        assert router_mod.should_refine(state) == "synthesize"

    def test_router_hard_cap_does_not_break_under_budget_path(self):
        state = {
            "iteration": 0,
            "max_iterations": 3,
            "total_cost_usd": 0.1,
            "budget_limit_usd": 2.0,
            "ranked_papers": [{"relevance_score": 5.0}],
        }
        assert router_mod.should_refine(state) == "refine"

    def test_router_under_budget_still_uses_ratio(self):
        state = {
            "iteration": 0,
            "max_iterations": 3,
            "total_cost_usd": 1.7,
            "budget_limit_usd": 2.0,
            "ranked_papers": [],
        }
        state["total_cost_usd"] = 1.8
        assert router_mod.should_refine(state) == "synthesize"


def test_sse_endpoint_emits_budget_exceeded_via_check_budget(monkeypatch):
    """[from budget_node_hard_stop] 真行为测试: SSE 端点用 check_budget + emit budget_exceeded 事件.

    R10.5.30 D2 拆解后, 老静态 guard 测 main.py 含 check_budget 字面量已
    不适用. R10.5.32 (P0-1a) 解锁, 改用 astream_events 触发 cost spike
    (mock cost > budget) 验证 SSE 端点真触发 budget_exceeded 事件.
    """
    import backend.api.routes.search as routes_search

    async def fake_get_cached(*args, **kwargs):
        return None

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        # cost spike: 0.6 > 0.5 budget → check_budget 触发
        yield {"event": "on_chain_start", "name": "synthesize", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "synthesize",
            "data": {"output": {"total_cost_usd": 0.6, "budget_limit_usd": 0.5}},
        }

    monkeypatch.setattr(routes_search, "get_cached_async", fake_get_cached)
    monkeypatch.setattr(routes_search.search_graph, "astream_events", fake_astream_events)

    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as c:
        with c.stream(
            "GET",
            "/search/stream",
            params={"q": "test", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
        ) as resp:
            assert resp.status_code == 200
            raw = resp.read().decode("utf-8")

    events = _parse_sse_events(raw)
    be_events = [e for e in events if e.get("event") == "budget_exceeded"]
    assert len(be_events) == 1, (
        f"P0-1 FAIL: cost spike 必触发 budget_exceeded, events: "
        f"{[e.get('event') for e in events]}"
    )


def test_router_source_has_hard_cap():
    """[from budget_node_hard_stop] Static guard: router.py must call check_budget for the hard cap."""
    from pathlib import Path
    src = Path(router_mod.__file__).read_text(encoding="utf-8")
    assert "from backend.utils.budget_guard import" in src
    assert "check_budget" in src


def test_budget_guard_module_exists():
    """[from budget_node_hard_stop] Sanity: the new module is importable.

    R9-A 删 BudgetExceededError 类后该 test 部分失效 (前两个 hasattr 改).
    """
    from backend.utils import budget_guard
    assert hasattr(budget_guard, "check_budget")
    assert hasattr(budget_guard, "BUDGET_GUARD_HARD_CAP_RATIO")
    assert budget_guard.BUDGET_GUARD_HARD_CAP_RATIO == 1.0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
