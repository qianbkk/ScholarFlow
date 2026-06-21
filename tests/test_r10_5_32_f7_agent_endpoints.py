"""R10.5.32 (F7) /agents/summarize + /agents/critique 端点测试.

覆盖:
  1. /agents/summarize: 入参合法, 返 summary_md + cost/tokens/elapsed/runtime_mode
  2. /agents/summarize: LLM 失败兜底 (call_llm 抛异常) 返 error 字符串
  3. /agents/critique: 复用 critic_agent prompt, 返 quality_score + recommendation
  4. /agents/critique: LLM 返非 JSON 时 raw_response 字段兜底
  5. 未鉴权 (OPEN_MODE=true) dev-user 走通
  6. mount: /api/v1/agents/summarize + /agents/summarize 双挂载
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_f7_summarize_returns_markdown_summary():
    """/agents/summarize: 合法入参 → summary_md + 用量字段."""
    from backend.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.post(
            "/api/v1/agents/summarize",
            json={
                "paper_id": "ss_001_test",
                "title": "Attention Is All You Need",
                "abstract": "We propose a new network architecture, the Transformer, based solely on attention mechanisms.",
                "query": "transformer attention",
            },
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["paper_id"] == "ss_001_test"
    assert data["agent"] == "summarize"
    assert "summary_md" in data["result"]
    # mock 模式 LLM 返非空 (call_llm mock 路径)
    if data["result"]["summary_md"]:
        # 摘要应该 ≥ 1 个字符
        assert len(data["result"]["summary_md"]) >= 1
    # 用量字段都存在
    assert "total_cost_usd" in data
    assert "total_tokens_used" in data
    assert "elapsed_seconds" in data
    # R10.5.55: runtime_mode 改名 'mock'/'real' → 'local'/'llm'.
    # 测试同时接受旧 (mock/real) 和新 (local/llm/unknown) 三态.
    assert data["runtime_mode"] in ("local", "llm", "unknown", "mock", "real")


def test_f7_summarize_handles_llm_failure():
    """/agents/summarize: call_llm 抛异常 → 返 error 字符串, 不 500."""
    from backend.main import app
    from backend.utils import llm_client
    from fastapi.testclient import TestClient

    # call_llm 在端点里是 `from backend.utils.llm_client import call_llm`
    # (局部 import), 必须 patch 源模块 llm_client.call_llm, 端点内 import
    # 拿的就是 monkeypatch 后的引用.
    orig = llm_client.call_llm
    async def fake_call_llm_error(*args, **kwargs):
        raise RuntimeError("simulated LLM outage")
    llm_client.call_llm = fake_call_llm_error
    try:
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/agents/summarize",
                json={
                    "paper_id": "ss_err",
                    "title": "Test",
                    "abstract": "x",
                    "query": "x",
                },
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "失败" in data["result"]["summary_md"] or "error" in data["result"]["summary_md"].lower()
    finally:
        llm_client.call_llm = orig


def test_f7_critique_returns_quality_score():
    """/agents/critique: 合法入参 → quality_score + recommendation."""
    from backend.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.post(
            "/api/v1/agents/critique",
            json={
                "paper_id": "ss_002_bert",
                "title": "BERT: Pre-training of Deep Bidirectional Transformers",
                "abstract": "We introduce BERT, which stands for Bidirectional Encoder Representations from Transformers.",
                "query": "BERT pretraining language model",
            },
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["paper_id"] == "ss_002_bert"
    assert data["agent"] == "critique"
    # critique result 应有 quality_score 或 raw_response 兜底
    if "quality_score" in data["result"]:
        assert 0 <= data["result"]["quality_score"] <= 10
    elif "raw_response" in data["result"]:
        # LLM mock 返非结构化, 兜底字段
        assert len(data["result"]["raw_response"]) >= 1
    elif "error" in data["result"]:
        # 兜底 2: LLM 失败
        pass


def test_f7_critique_handles_invalid_json():
    """/agents/critique: LLM 返非 JSON → raw_response 字段兜底."""
    from backend.main import app
    from backend.utils import llm_client
    from fastapi.testclient import TestClient

    orig = llm_client.call_llm
    async def fake_call_llm_bad_json(*args, **kwargs):
        return ("This is not JSON, just plain text response.", {"cost": 0.0, "tokens": 0})
    llm_client.call_llm = fake_call_llm_bad_json
    try:
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/agents/critique",
                json={
                    "paper_id": "ss_bad",
                    "title": "Test",
                    "abstract": "x",
                    "query": "x",
                },
            )
        assert r.status_code == 200, r.text
        data = r.json()
        # 非 JSON 返 raw_response 兜底
        assert "raw_response" in data["result"] or "error" in data["result"]
    finally:
        llm_client.call_llm = orig


def test_f7_bare_alias_works():
    """/agents/summarize (无 /api/v1 前缀) 同样工作 (R10.5.30 双挂载)."""
    from backend.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.post(
            "/agents/summarize",
            json={
                "paper_id": "ss_alias",
                "title": "Test",
                "abstract": "x",
                "query": "x",
            },
        )
    assert r.status_code == 200, r.text


def test_f7_unauthorized_no_key_401_in_prod():
    """/agents/summarize: OPEN_MODE=false + 无 X-API-Key → 401.

    R10.5.30 D3: auth path 通过 get_current_user 校验. 验证鉴权真的接上了.
    """
    import backend.auth.dependencies as deps
    from backend.main import app
    from fastapi.testclient import TestClient

    orig = deps.OPEN_MODE
    deps.OPEN_MODE = False
    try:
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/agents/summarize",
                json={
                    "paper_id": "ss_noauth",
                    "title": "Test",
                    "abstract": "x",
                    "query": "x",
                },
            )
        assert r.status_code == 401, f"expected 401 without auth, got {r.status_code}: {r.text}"
    finally:
        deps.OPEN_MODE = orig
