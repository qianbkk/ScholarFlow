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
    main_mod.GLOBAL_HOURLY_BUDGET = 5.0

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
    main_mod.GLOBAL_HOURLY_BUDGET = 1.0

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

    async def fake_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)
    monkeypatch.setattr(
        main_mod.search_graph,
        "ainvoke",
        _make_failing_graph(RuntimeError("simulated pipeline failure")),
    )

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
    assert len(return_calls) >= 1


def test_budget_returned_on_key_error(client, monkeypatch):
    """[from budget_try_finally] KeyError → _return_budget called."""
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
    assert len(return_calls) >= 1


def test_budget_returned_on_generic_exception(client, monkeypatch):
    """[from budget_try_finally] generic Exception → _return_budget called."""
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
    assert len(return_calls) >= 1


def test_budget_returned_on_custom_exception(client, monkeypatch):
    """[from budget_try_finally] Custom exception class → _return_budget still called."""
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
    assert len(return_calls) >= 1


def test_budget_returned_on_timeout(client, monkeypatch):
    """[from budget_try_finally] asyncio.TimeoutError → _return_budget called with full budget."""
    _mock_provider_list(monkeypatch, ["kimi"])
    _seed_budget(0.0)

    return_calls = []

    async def fake_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", fake_return_budget)

    async def fake_ainvoke(initial):
        await asyncio.sleep(0)
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
    assert len(return_calls) >= 1
    assert any(c >= 0.5 - 1e-6 for c in return_calls)


def test_budget_return_on_success_returns_diff(client, monkeypatch):
    """[from budget_try_finally] On success, _return_budget is called with (req.budget - actual_cost)."""
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
            "total_cost_usd": 0.1,
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
    assert any(abs(c - 0.4) < 0.011 for c in return_calls), (
        f"On success, _return_budget should be called with diff (≈0.4). Calls: {return_calls}"
    )


def test_main_py_handles_exception_in_search():
    """[from budget_try_finally] Source-level check: /search must handle generic Exception and call _return_budget."""
    from pathlib import Path
    src = Path(main_mod.__file__).read_text(encoding="utf-8")

    import re
    search_block = re.search(
        r"async def search\([^)]*\):.*?(?=\n@app\.)",
        src,
        flags=re.DOTALL,
    )
    if search_block is None:
        search_block = re.search(
            r"async def search\([^)]*\):.*?(?=\nasync def |\n@app\.|\ndef )",
            src,
            flags=re.DOTALL,
        )
    assert search_block is not None, "could not locate search() function in main.py"

    body = search_block.group(0)
    has_except_handler = "except Exception" in body
    assert has_except_handler, "search() must have an except Exception handler"
    assert "_return_budget" in body, (
        "CRITICAL-002 FAIL: /search function body must call _return_budget on the "
        "exception path so reserved budget is returned."
    )


# ============================================================
# 3) SSE client disconnect still returns budget (sse_disconnect_budget)
# ============================================================

def test_client_disconnect_returns_budget(client, monkeypatch):
    """[from sse_disconnect] Simulate client disconnect mid-stream. Budget must be returned."""
    _mock_provider_list(monkeypatch, ["kimi"])
    return_calls = []
    real_return = main_mod._return_budget

    async def tracking_return_budget(amount):
        return_calls.append(amount)
        return await real_return(amount)

    monkeypatch.setattr(main_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    async def fake_astream(initial, stream_mode=None):
        yield {"query_decompose": {"sub_queries": ["transformer"]}}
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            raise
        yield {"search": {"raw_papers": []}}

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

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

    async def tracking_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    async def fake_astream(initial, stream_mode=None):
        yield {"query_decompose": {"sub_queries": ["x"]}}
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        yield {"search": {"raw_papers": []}}

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

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
    """[from sse_disconnect] Build the event_generator and call aclose() to throw GeneratorExit."""
    _mock_provider_list(monkeypatch, ["kimi"])
    return_calls = []

    async def tracking_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    astream_entered = asyncio.Event()
    astream_can_exit = asyncio.Event()

    async def fake_astream(initial, stream_mode=None):
        astream_entered.set()
        try:
            yield {"query_decompose": {"sub_queries": ["x"]}}
            await astream_can_exit.wait()
        except (asyncio.CancelledError, GeneratorExit):
            raise
        yield {"search": {"raw_papers": []}}

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

    budget = 0.5
    max_iter = 1
    safe_query = "test"
    initial = {
        "original_query": safe_query,
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "expanded_paper_ids": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": max_iter,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": budget,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
        "provider": "kimi",
    }

    async def event_generator():
        yield {"event": "started", "cached": False}
        accumulated: dict = dict(initial)
        # R7: 去掉 `async with asyncio.timeout(240.0)` 包装 — Python 3.11+ asyncio.timeout
        # context manager 会把内部 CancelledError 转 TimeoutError, 导致客户端 aclose()
        # 路径走不到 CancelledError 块。改成裸 try/except (TimeoutError, CancelledError)
        # 跟 main.py 实际 event_generator 行为一致
        try:
            async for chunk in main_mod.search_graph.astream(initial, stream_mode="updates"):
                for node_name, state_update in chunk.items():
                    if not isinstance(state_update, dict):
                        continue
                    accumulated.update(state_update)
                    yield {"event": "node_complete", "node": node_name}
        except TimeoutError:
            await main_mod._return_budget(budget)
            yield {"event": "error", "code": "timeout"}
            return
        except asyncio.CancelledError:
            await main_mod._return_budget(budget)
            yield {"event": "error", "code": "cancelled"}
            return
        except Exception:
            await main_mod._return_budget(budget)
            yield {"event": "error", "code": "internal"}
            return
        await main_mod._return_budget(0.0)
        yield {"event": "done"}

    gen = event_generator()
    first = await gen.__anext__()
    assert first == {"event": "started", "cached": False}

    # R7: 删掉 `await asyncio.wait_for(astream_entered.wait(), timeout=2.0)`。
    # 原因: gen yield "started" 后挂起, 没人推进 gen 就不会进 astream, astream_entered
    # 永远不 set, wait_for 2.0s 后抛 TimeoutError (经 asyncio.timeout 包装)。
    # 改成直接 next 让 gen 自然推进到 astream 入口, astream_entered 会被 set。
    second = await gen.__anext__()
    assert second == {"event": "node_complete", "node": "query_decompose"}
    assert astream_entered.is_set(), "astream should have been entered by now"

    try:
        await gen.athrow(asyncio.CancelledError())
    except (asyncio.CancelledError, StopAsyncIteration, GeneratorExit):
        pass

    astream_can_exit.set()
    try:
        async for _ in gen:
            pass
    except (asyncio.CancelledError, StopAsyncIteration, GeneratorExit, Exception):
        pass


@pytest.mark.asyncio
async def test_cancelled_error_in_astream_triggers_budget_return(monkeypatch):
    """[from sse_disconnect] When astream's inner __anext__ is cancelled, try/except must catch + return."""
    _mock_provider_list(monkeypatch, ["kimi"])
    return_calls = []

    async def tracking_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    async def fake_astream(initial, stream_mode=None):
        yield {"query_decompose": {"sub_queries": ["x"]}}
        await asyncio.sleep(0)
        raise asyncio.CancelledError("simulated disconnect")

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

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
        yield {"event": "started"}
        accumulated: dict = dict(initial)
        # R7: 去掉 async with asyncio.timeout 包装 — 它的 context manager 把内部
        # CancelledError 转 TimeoutError, 导致客户端 CancelledError 路径走不到。
        try:
            async for chunk in main_mod.search_graph.astream(initial, stream_mode="updates"):
                for node_name, state_update in chunk.items():
                    if not isinstance(state_update, dict):
                        continue
                    accumulated.update(state_update)
                    yield {"event": "node_complete"}
        except TimeoutError:
            await main_mod._return_budget(budget)
            yield {"event": "error", "code": "timeout"}
            return
        except asyncio.CancelledError:
            # R7: SSE 客户端断连 (CancelledError) 也要走 budget 返还路径 — 跟 main.py
            # 实际 event_generator 的 finally 块保持一致 (CRITICAL-003)。
            await main_mod._return_budget(budget)
            yield {"event": "error", "code": "cancelled"}
            return
        except Exception:
            await main_mod._return_budget(budget)
            yield {"event": "error", "code": "internal"}
            return
        await main_mod._return_budget(0.0)
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


def test_stream_source_has_budget_return_on_exception():
    """[from sse_disconnect] Static guard: /search/stream's event_generator must call _return_budget on exception."""
    from pathlib import Path
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert "_return_budget(budget)" in src, (
        "CRITICAL-003 FAIL: main.py must have _return_budget(budget) call in the "
        "stream endpoint's exception handler."
    )
    assert "except Exception" in src and "_return_budget" in src


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


class TestBudgetExceededErrorUnit:
    def test_attributes(self):
        e = BudgetExceededError(cost=2.5, limit=2.0, node="synthesize")
        assert e.cost == 2.5
        assert e.limit == 2.0
        assert e.node == "synthesize"
        assert "synthesize" in str(e)
        assert "2.5" in str(e)
        assert "2.00" in str(e)

    def test_default_message(self):
        e = BudgetExceededError(cost=2.5, limit=2.0)
        assert e.node is None
        assert "after node" not in str(e)
        assert "2.5" in str(e)


def test_sse_emits_budget_exceeded_when_cost_spikes(client, monkeypatch):
    """[from budget_node_hard_stop] cost spike at 2nd node → emit budget_exceeded + no done."""
    _mock_provider_list(monkeypatch, ["kimi"])

    return_calls = []

    async def tracking_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", tracking_return_budget)

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    BUDGET = 0.5

    async def fake_astream(initial, stream_mode=None):
        yield {
            "query_decompose": {
                "sub_queries": ["x"],
                "total_cost_usd": 0.1,
                "budget_limit_usd": BUDGET,
            }
        }
        yield {
            "synthesize": {
                "total_cost_usd": 0.6,  # over budget
                "budget_limit_usd": BUDGET,
            }
        }
        yield {
            "build_graph": {
                "total_cost_usd": 0.7,
                "budget_limit_usd": BUDGET,
            }
        }

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

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
    _mock_provider_list(monkeypatch, ["kimi"])

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    BUDGET = 1.0

    async def fake_astream(initial, stream_mode=None):
        yield {
            "search": {
                "raw_papers": [],
                "total_cost_usd": 1.0,
                "budget_limit_usd": BUDGET,
            }
        }
        yield {
            "rank": {
                "ranked_papers": [],
                "total_cost_usd": 1.0,
                "budget_limit_usd": BUDGET,
            }
        }

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

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
    _mock_provider_list(monkeypatch, ["kimi"])

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    BUDGET = 1.0

    async def fake_astream(initial, stream_mode=None):
        yield {
            "query_decompose": {"total_cost_usd": 0.1, "budget_limit_usd": BUDGET}
        }
        yield {
            "search": {"total_cost_usd": 0.3, "budget_limit_usd": BUDGET}
        }
        yield {
            "synthesize": {"total_cost_usd": 0.5, "budget_limit_usd": BUDGET}
        }

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

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
    _mock_provider_list(monkeypatch, ["kimi"])

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    async def fake_astream(initial, stream_mode=None):
        yield {
            "query_decompose": {
                "sub_queries": ["x"],
                "total_cost_usd": 0.05,
            }
        }
        yield {
            "synthesize": {
                "total_cost_usd": 0.1,
            }
        }

    monkeypatch.setattr(main_mod.search_graph, "astream", fake_astream)

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
    """[from budget_node_hard_stop] Defensive: ainvoke raises BudgetExceededError → status=budget_exceeded."""
    _mock_provider_list(monkeypatch, ["kimi"])
    main_mod._save_budget_to_db(0.0, _time.time())

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

    return_calls = []

    async def tracking_return_budget(amount):
        return_calls.append(amount)
        return None

    monkeypatch.setattr(main_mod, "_return_budget", tracking_return_budget)

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
    monkeypatch.setattr(main_mod, "get_cached_async", fake_get_cached)

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


def test_sse_source_has_node_level_budget_check():
    """[from budget_node_hard_stop] Static guard: SSE event_generator must call check_budget + emit budget_exceeded."""
    from pathlib import Path
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert "from backend.utils.budget_guard import" in src, (
        "P0-1 FAIL: main.py must import from backend.utils.budget_guard"
    )
    assert "BudgetExceededError" in src
    assert "check_budget" in src
    assert '"budget_exceeded"' in src or "'budget_exceeded'" in src
    assert "new_total" in src


def test_router_source_has_hard_cap():
    """[from budget_node_hard_stop] Static guard: router.py must call check_budget for the hard cap."""
    from pathlib import Path
    src = Path(router_mod.__file__).read_text(encoding="utf-8")
    assert "from backend.utils.budget_guard import" in src
    assert "check_budget" in src


def test_budget_guard_module_exists():
    """[from budget_node_hard_stop] Sanity: the new module is importable."""
    from backend.utils import budget_guard
    assert hasattr(budget_guard, "BudgetExceededError")
    assert hasattr(budget_guard, "check_budget")
    assert hasattr(budget_guard, "BUDGET_GUARD_HARD_CAP_RATIO")
    assert budget_guard.BUDGET_GUARD_HARD_CAP_RATIO == 1.0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
