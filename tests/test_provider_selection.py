"""Tests for the user-selectable LLM provider feature.

新增端点 `GET /providers` + `provider` 参数（在 /search 和 /search/stream 中接受）。
本测试覆盖：
  1) `GET /providers` 返回 default_provider + providers 列表
  2) has_key 字段反映 *实际* 环境变量状态（有 key 的 provider → True）
  3) `POST /search` 收到无效 provider → 400
  4) `POST /search` 收到有效 provider（当前环境已配置 key）→ 200
"""
import pytest


def _build_test_client():
    """构造一个干净的 FastAPI TestClient。

    显式 import 在函数体内（不在模块顶部）— 避免与 test_cors_hardening.py
    的 sys.modules purge 冲突（那是模块级 import 留下的 stale reference）。
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)


def test_get_providers_endpoint_returns_list():
    """GET /providers 必须返回 default_provider + providers 列表。"""
    client = _build_test_client()
    resp = client.get("/providers")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "default_provider" in body, f"missing default_provider in {body}"
    assert "providers" in body, f"missing providers in {body}"
    assert isinstance(body["providers"], list), f"providers not a list: {body['providers']}"
    assert len(body["providers"]) >= 1, "providers list should not be empty"

    # 每个 provider 必须有完整 schema
    required_keys = {"id", "name", "flagship_model", "fast_model", "has_key"}
    for p in body["providers"]:
        assert required_keys.issubset(p.keys()), (
            f"provider {p.get('id')!r} missing keys: {required_keys - p.keys()}"
        )
        assert isinstance(p["has_key"], bool)
        assert p["id"] in {"kimi", "glm", "minimax", "anthropic", "deepseek"}


def test_get_providers_only_includes_has_key_true_for_configured():
    """has_key 字段必须与对应 *_API_KEY env var 一致。"""
    import os
    import backend.config as cfg_mod

    client = _build_test_client()
    resp = client.get("/providers")
    assert resp.status_code == 200
    body = resp.json()

    # 期望 has_key 状态
    expected = {
        "kimi": bool(cfg_mod.KIMI_API_KEY),
        "glm": bool(cfg_mod.GLM_API_KEY),
        "minimax": bool(cfg_mod.MiniMax_API_KEY),
        "anthropic": bool(cfg_mod.ANTHROPIC_API_KEY),
        "deepseek": bool(cfg_mod.DEEPSEEK_API_KEY),
    }
    by_id = {p["id"]: p for p in body["providers"]}
    for pid, want in expected.items():
        if pid in by_id:
            got = by_id[pid]["has_key"]
            assert got == want, (
                f"provider {pid!r}: expected has_key={want}, got {got}"
            )


def test_get_providers_at_least_one_has_key_in_normal_env():
    """在 .env 已配置 key 的环境里，至少应有一个 provider 的 has_key=True。

    若当前 .env 完全没有 key，所有 provider 的 has_key 都为 False — 这是合法
    状态（前端会显示空下拉并提示用户配置 .env），但为了实际可用性断言至少一个
    True。Mock 模式下也仍然至少有 1 个（任何 provider 都可手动 setenv 验证）。
    """
    import backend.config as cfg_mod

    has_any = any([
        cfg_mod.KIMI_API_KEY, cfg_mod.GLM_API_KEY, cfg_mod.MiniMax_API_KEY,
        cfg_mod.ANTHROPIC_API_KEY, cfg_mod.DEEPSEEK_API_KEY,
    ])
    if not has_any:
        pytest.skip(
            "当前 .env 未配置任何 LLM key（all has_key=False 是合法但需手动 setenv 测试）"
        )

    client = _build_test_client()
    body = client.get("/providers").json()
    any_true = any(p["has_key"] for p in body["providers"])
    assert any_true, f"expected at least one provider with has_key=True, got {body}"


def test_search_with_invalid_provider_returns_400():
    """POST /search provider='nonexistent' → 400 with helpful message."""
    client = _build_test_client()
    resp = client.post(
        "/search",
        json={
            "query": "transformer attention",
            "budget": 1.0,
            "max_iterations": 1,
            "provider": "nonexistent",
        },
    )
    assert resp.status_code == 400, (
        f"expected 400, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "nonexistent" in detail or "provider" in detail.lower(), (
        f"error message should mention the bad provider, got: {detail!r}"
    )


def test_search_with_empty_provider_uses_default(monkeypatch):
    """POST /search provider='' 或 None → 走 LLM_PROVIDER env（不应 400）。

    Mock 掉 graph.ainvoke 让 endpoint 快速返回 — 只验证 provider 解析逻辑
    （空字符串 → 默认 provider，不应 400）不会触发完整 8 节点流水线。
    """
    import asyncio
    import backend.main as main_mod

    # Stub search_graph.ainvoke — 只返回 minimal state，跳过真实流水线
    async def fake_ainvoke(initial):
        return {
            "report": "stub",
            "ranked_papers": [],
            "citation_graph": {},
            "total_cost_usd": 0.0,
            "total_tokens_used": 0,
            "model_usage": {},
            "iteration": 0,
            "status": "done",
        }
    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)

    client = _build_test_client()
    resp = client.post(
        "/search",
        json={
            "query": "test",
            "budget": 1.0,
            "max_iterations": 1,
            "provider": "",
        },
    )
    # 不应 400 — 空字符串是合法（"用默认"）的语义
    assert resp.status_code != 400, f"empty provider should fall through to default, got {resp.text}"


def test_search_with_valid_provider_runs(monkeypatch):
    """POST /search provider='minimax' → 200 (provider 解析通过)。

    Mock 掉 graph.ainvoke 让 endpoint 快速返回 — 不真正跑 8 节点流水线。
    端到端测试见 tests/manual/ 下的 Playwright 脚本。
    """
    import backend.main as main_mod

    async def fake_ainvoke(initial):
        return {
            "report": "stub",
            "ranked_papers": [],
            "citation_graph": {},
            "total_cost_usd": 0.0,
            "total_tokens_used": 0,
            "model_usage": {},
            "iteration": 0,
            "status": "done",
        }
    monkeypatch.setattr(main_mod.search_graph, "ainvoke", fake_ainvoke)

    client = _build_test_client()
    resp = client.post(
        "/search",
        json={
            "query": "transformer attention mechanism",
            "budget": 1.0,
            "max_iterations": 1,
            "provider": "minimax",
        },
    )
    # 200 = 成功；非 400/422（说明 provider 校验通过）
    assert resp.status_code == 200, (
        f"expected 200, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "report" in body
    assert "ranked_papers" in body


def test_search_stream_with_invalid_provider_returns_400():
    """GET /search/stream provider='nope' → 400。"""
    client = _build_test_client()
    resp = client.get(
        "/search/stream",
        params={
            "q": "test",
            "budget": 1.0,
            "max_iter": 1,
            "provider": "nope",
        },
    )
    assert resp.status_code == 400, (
        f"expected 400, got {resp.status_code}: {resp.text}"
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
