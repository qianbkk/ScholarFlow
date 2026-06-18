"""R10.5.45 测试: SSE id 字段 + last_event_id query 接收 (P0/P1 SSE 续传基础设施).

覆盖:
  1. 每个 SSE 事件 emit id: <n>\n 字段 (n 单调递增)
  2. last_event_id query param 被读取 + 日志记录
  3. 缓存命中路径也带 id
  4. 错误事件 (timeout / cancelled / internal) 也带 id
  5. SSE id 字段是 Optional[int] 类型, 客户端可解析
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _parse_sse_raw_block(block: str) -> tuple[int | None, dict | None]:
    """解析一个 SSE block: 返回 (id, data_dict). None = 字段缺失."""
    sse_id = None
    sse_data = None
    for line in block.split("\n"):
        if line.startswith("id: "):
            try:
                sse_id = int(line[4:].strip())
            except ValueError:
                pass
        elif line.startswith("data: "):
            try:
                sse_data = json.loads(line[6:])
            except (json.JSONDecodeError, ValueError):
                pass
    return sse_id, sse_data


def _collect_sse_blocks(raw: str) -> list[tuple[int | None, dict | None]]:
    """按 \\n\\n 切分 SSE 块, 解析每块."""
    blocks: list[tuple[int | None, dict | None]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        blocks.append(_parse_sse_raw_block(block))
    return blocks


# ===== 1. 每个 SSE 事件 emit id 字段 =====

@pytest.mark.asyncio
async def test_sse_events_emit_monotonic_ids(monkeypatch):
    """[/search/stream] 每个事件必须 emit id: <n>\\n, n 从 0 单调递增."""
    from backend.api.routes import search as search_mod
    import backend.main as main_mod

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        # 模拟完整 8 节点流水线
        nodes = [
            "query_decompose", "search", "expand_citations", "rank",
            "synthesize", "build_graph", "track_cost",
        ]
        for node in nodes:
            yield {"event": "on_chain_start", "name": node, "data": {}}
            yield {
                "event": "on_chain_end",
                "name": node,
                "data": {"output": {
                    "total_cost_usd": 0.05,
                    "total_tokens_used": 100,
                    "iteration": 0,
                }},
            }

    monkeypatch.setattr(search_mod.search_graph, "astream_events", fake_astream_events)

    with TestClient(main_mod.app) as client:
        resp = client.get(
            "/api/v1/search/stream",
            params={"q": "test_sse_ids", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
        )
        assert resp.status_code == 200
        raw = resp.text

    blocks = _collect_sse_blocks(raw)
    # 至少要 8+ 个事件 (started + 7 节点 * 2 = 15+)
    assert len(blocks) >= 14, f"Expected 14+ SSE events, got {len(blocks)}: {blocks[:3]}"

    # 验证每个有 id 字段
    for i, (sse_id, data) in enumerate(blocks):
        assert sse_id is not None, (
            f"Event #{i} missing 'id:' field: data={data}"
        )

    # 验证 id 单调递增
    ids = [sse_id for sse_id, _ in blocks if sse_id is not None]
    for i in range(1, len(ids)):
        assert ids[i] == ids[i-1] + 1, (
            f"Event id not monotonic: ids={ids}"
        )

    # 验证 id 从 0 开始
    assert ids[0] == 0, f"First id should be 0, got {ids[0]}"


# ===== 2. last_event_id query param 接收 =====

@pytest.mark.asyncio
async def test_last_event_id_query_param_accepted_and_logged(monkeypatch, caplog):
    """[/search/stream] ?last_event_id=N 必须被接收 + 记日志 (R10.5.45 仅 log, R11+ 真续)."""
    from backend.api.routes import search as search_mod
    import backend.main as main_mod
    import logging

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "query_decompose",
            "data": {"output": {"sub_queries": ["x"]}},
        }

    monkeypatch.setattr(search_mod.search_graph, "astream_events", fake_astream_events)

    with caplog.at_level(logging.INFO, logger="backend.api.routes.search"):
        with TestClient(main_mod.app) as client:
            resp = client.get(
                "/api/v1/search/stream",
                params={
                    "q": "test_resume",
                    "max_iter": 1,
                    "budget": 0.5,
                    "provider": "kimi",
                    "last_event_id": 42,
                },
            )
            assert resp.status_code == 200

    # 验证日志包含 last_event_id=42
    log_text = "\n".join(record.message for record in caplog.records)
    assert "last_event_id=42" in log_text, (
        f"Expected log to mention last_event_id=42, got: {log_text[:500]}"
    )


# ===== 3. last_event_id 可选, 不传也能正常工作 =====

@pytest.mark.asyncio
async def test_stream_works_without_last_event_id(monkeypatch):
    """[/search/stream] 不传 last_event_id 时, 行为跟之前一样 (向后兼容)."""
    from backend.api.routes import search as search_mod
    import backend.main as main_mod

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "query_decompose",
            "data": {"output": {"sub_queries": ["x"]}},
        }

    monkeypatch.setattr(search_mod.search_graph, "astream_events", fake_astream_events)

    with TestClient(main_mod.app) as client:
        resp = client.get(
            "/api/v1/search/stream",
            params={"q": "no_resume", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
        )
        assert resp.status_code == 200
        # 必须有 started + node_complete
        blocks = _collect_sse_blocks(resp.text)
        events_seen = [d.get("event") for _, d in blocks if d]
        assert "started" in events_seen
        assert "node_complete" in events_seen


# ===== 4. 错误事件也带 id =====

@pytest.mark.asyncio
async def test_error_events_also_emit_ids(monkeypatch):
    """[/search/stream] 错误事件 (timeout / cancelled / client_disconnected)
    也必须 emit id, 客户端能正确追踪最后收到的位置."""
    from backend.api.routes import search as search_mod
    import backend.main as main_mod

    async def fake_get_cached(*args, **kwargs):
        return None
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    async def fake_astream_events(initial, stream_mode=None, **kwargs):
        yield {"event": "on_chain_start", "name": "query_decompose", "data": {}}
        # 抛 CancelledError 模拟 client 断开
        raise asyncio.CancelledError("simulated")

    monkeypatch.setattr(search_mod.search_graph, "astream_events", fake_astream_events)

    with TestClient(main_mod.app) as client:
        try:
            with client.stream(
                "GET",
                "/api/v1/search/stream",
                params={"q": "err_test", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
            ) as resp:
                assert resp.status_code == 200
                raw = ""
                for line in resp.iter_lines():
                    raw += line + "\n"
                    if '"cancelled"' in line:
                        break
                resp.close()
        except Exception:
            raw = ""

    blocks = _collect_sse_blocks(raw)
    # 验证 cancelled 错误事件有 id
    cancelled_blocks = [
        (sse_id, data) for sse_id, data in blocks
        if data and data.get("code") == "cancelled"
    ]
    assert len(cancelled_blocks) >= 1, f"Expected cancelled event, got: {blocks}"
    sse_id, data = cancelled_blocks[0]
    assert sse_id is not None, "cancelled event missing 'id:' field"
    assert isinstance(sse_id, int), f"cancelled id should be int, got {type(sse_id)}"


# ===== 5. 缓存命中路径也带 id =====

@pytest.mark.asyncio
async def test_cache_hit_path_also_emits_ids(monkeypatch):
    """[/search/stream] 缓存命中快速返回路径, started + done 也必须带 id."""
    from backend.api.routes import search as search_mod
    import backend.main as main_mod

    async def fake_get_cached(*args, **kwargs):
        return (
            {"report": "cached", "ranked_papers": [], "citation_graph": {}},
            0.01,
            100,
        )
    monkeypatch.setattr(search_mod, "get_cached_async", fake_get_cached)

    with TestClient(main_mod.app) as client:
        resp = client.get(
            "/api/v1/search/stream",
            params={"q": "cache_id_test", "max_iter": 1, "budget": 0.5, "provider": "kimi"},
        )
        assert resp.status_code == 200
        raw = resp.text

    blocks = _collect_sse_blocks(raw)
    assert len(blocks) >= 2, f"Expected 2 events (started + done), got {len(blocks)}"

    # 验证 started 和 done 都有 id
    started_blocks = [(sse_id, data) for sse_id, data in blocks if data and data.get("event") == "started"]
    done_blocks = [(sse_id, data) for sse_id, data in blocks if data and data.get("event") == "done"]
    assert len(started_blocks) >= 1
    assert started_blocks[0][0] is not None, "started event missing id"
    assert len(done_blocks) >= 1
    assert done_blocks[0][0] is not None, "done event missing id"

    # id 单调: done.id > started.id
    assert done_blocks[0][0] > started_blocks[0][0]
