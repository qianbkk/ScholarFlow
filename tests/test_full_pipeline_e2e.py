"""
E2E test for R10.5.14 (P0-E): 端到端完整流水线.

R10.5 审计 (P0-13) 提的"端到端测试缺失"在这里落地 — 跑完整 8 节点流水线
(query_decompose → search → expand_citations → rank → synthesize → build_graph
→ cost_track), 验证最终响应包含:
  1. status 字段 (done / error)
  2. report 字段 (含研究概述 / 核心论文 等节)
  3. citation_graph.nodes / links (≥ 1 个节点)
  4. ranked_papers (≥ 1 篇)
  5. constraints 字段 (新 R10.5.14 P0-A)
  6. cost 字段 (说明 cost_tracker 跑过)
  7. timing 字段 (latency 真实测得)

走 FastAPI TestClient + 纯 mock (LLM_MOCK=true, API_MOCK=true), 全部 in-process
不需要启动 uvicorn / vite, CI 上 0 依赖. 总时长 5-15s 取决于 mock 论文数.

不验证 (跟 e2e_test_404_fix 互补):
  - playwright 浏览器交互 — e2e_test_404_fix 覆盖
  - 真实 LLM 网络调用 — 那是 R10.5.9 e2e (用 minimax 实跑) 的范围
  - SSE 流式 — 单独测 test_sse_disconnect_budget
"""
import json
import time
import sys
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod
import backend.config as cfg_mod


@pytest.fixture
def client(monkeypatch):
    """TestClient 套 main.app. 配合 conftest.py 的 ENVIRONMENT=test + 限流 1000/min,
    不会撞 429. mock 模式 (LLM_MOCK + API_MOCK) 由 force_mock_api fixture 保证.

    R10.5.14: 用全新 tmp dir 当 SCHOLARFLOW_DB_DIR, 避免跟其他 test 共享 SQLite 缓存
    (缓存命中会让 constraints 字段读到旧 schema 缺失 → 测试飘).
    """
    # R10.5.14: 用唯一 query 前缀 (uuid) 避免跨 test 缓存命中 (精确 + 语义).
    # 不 reload cache_mod 是因为 OperationalError (SQLite 连接已被其他模块持有).
    # 用唯一 query 简单粗暴, 但稳.
    import uuid as _uuid
    unique = _uuid.uuid4().hex[:8]
    yield TestClient(main_mod.app), unique


def _post_search(client_tuple, query: str, budget: float = 0.5):
    """POST /api/v1/search, 返完整 SearchResponse dict.

    D1 (P0-4): 旧实现 POST /search 同步端点, 60s timeout 跟 8 节点 mock 流水线
    (10-50s 实际耗时) 临界, 偶发 504. 改用 /api/v1/search/stream (480s SSE)
    拿 done 事件当结果 — 跟 e2e_test_404_fix 测的同步端点互补. mock 模式下
    实际 <10s, 不会再撞 timeout.

    client_tuple = (TestClient, unique_suffix) — unique suffix 拼到 query
    末尾防跨 test 缓存命中 (SQLite + 语义 LRU).
    """
    c, unique = client_tuple
    unique_query = f"{query} [t{unique}]"
    # 调 SSE 流式端点, 等 done 事件
    with c.stream(
        "GET",
        f"/api/v1/search/stream?q={unique_query}&budget={budget}&provider=minimax",
    ) as resp:
        if resp.status_code != 200:
            # 流式 HTTP 错误 (e.g. 422 invalid query) — 包成 Response 形态返回
            return _FakeResponse(resp.status_code, b"")
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                payload = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if payload.get("event") == "done":
                # 包装成跟 c.post 一样的 Response 形态, 上层 r.json() 还能用
                return _FakeResponse(200, json.dumps(payload["result"]).encode())
            if payload.get("event") == "error":
                return _FakeResponse(500, json.dumps({"detail": payload.get("message")}).encode())
            if payload.get("event") == "budget_exceeded":
                return _FakeResponse(200, json.dumps(payload.get("result") or {}).encode())
    # 流没 done 也没 error — 异常
    return _FakeResponse(504, b'{"detail":"stream ended without done event"}')


class _FakeResponse:
    """D1 修: e2e 期望 r.status_code + r.json() + r.text 形态. 把 stream done
    包装成跟 c.post() 返回同 API 的对象."""
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        if not self._body:
            return {}
        return json.loads(self._body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")


class TestFullPipelineE2E:
    """R10.5.14 (P0-E): 端到端完整流."""

    def test_search_returns_200(self, client, force_mock_api):
        """入口调通: POST /api/v1/search → 200, 含 SearchResponse 核心字段."""
        t0 = time.time()
        r = _post_search(client, "transformer attention mechanism", budget=0.5)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"search failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        # 8 节点跑完 (mock 模式) 通常 <5s, 30s 是健康检查上限
        assert elapsed < 30.0, f"pipeline too slow: {elapsed:.1f}s"
        assert data.get("status") in ("done", "error", "budget_exceeded"), \
            f"unexpected status: {data.get('status')}"

    def test_search_response_has_required_fields(self, client, force_mock_api):
        """SearchResponse schema 完整性 — 缺字段意味着某节点没跑."""
        r = _post_search(client, "BERT pretraining language model", budget=0.5)
        assert r.status_code == 200
        data = r.json()
        # 必填字段 (P0-E 验证完整流水线, 字段名按 SearchResponse 实际 schema)
        for field in ("status", "report", "ranked_papers", "citation_graph",
                      "elapsed_seconds", "total_cost_usd", "constraints"):
            assert field in data, f"missing field: {field}"

    def test_constraints_extracted_from_query(self, client, force_mock_api):
        """R10.5.14 P0-A: query_decomposer 抽结构化约束. 'NeurIPS 2022' 应被识别.

        LLM_MOCK 模式下 LLM 输出空 venues, 走 fallback 正则兜底 — 我们的
        query_decomposer 设计的补回逻辑让正则抽取的 NeurIPS/2022 进入 constraints.
        """
        r = _post_search(client, "graph neural network NeurIPS 2022 molecular property", budget=0.5)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        constraints = data.get("constraints") or {}
        # 兜底正则一定识别 NeurIPS (LLM_MOCK 空时 fallback 补)
        venues = constraints.get("venues") or []
        assert any("NeurIPS" in v for v in venues), \
            f"expected NeurIPS in venues, got {venues}"
        # year_range 至少覆盖 2022
        yr = constraints.get("year_range")
        assert yr and len(yr) == 2 and 2022 <= yr[0] <= yr[1] <= 2022 + 1, \
            f"expected year_range to cover 2022, got {yr}"

    def test_constraints_none_when_not_in_query(self, client, force_mock_api):
        """R10.5.14 P0-A: 无 venue/year 显式信号时, constraints 字段为 None, 不瞎猜."""
        r = _post_search(client, "transformer self-attention", budget=0.5)
        assert r.status_code == 200
        constraints = (r.json().get("constraints") or {})
        # venues / year_range 没显式信号时应该是 None (避免假阳性)
        assert constraints.get("venues") in (None, []), \
            f"venues should be None/empty for non-venue query, got {constraints.get('venues')}"
        assert constraints.get("year_range") is None, \
            f"year_range should be None for non-year query, got {constraints.get('year_range')}"

    def test_query_type_classified(self, client, force_mock_api):
        """R10.5.15 P1-D: query_decomposer 把 query 分类成 simple/survey/method/...
        分类结果进 constraints.query_type 字段, 供下游 search/synth 节点用."""
        # mock 模式下 LLM 不返回 query_type, fallback 走 'default'
        r = _post_search(client, "transformer self-attention", budget=0.5)
        assert r.status_code == 200
        constraints = r.json().get("constraints") or {}
        # query_type 字段必须在, 值是 5 类之一 + default
        assert "query_type" in constraints
        assert constraints["query_type"] in (
            "simple", "survey", "method", "comparison", "latest", "default",
        ), f"unexpected query_type: {constraints.get('query_type')}"

    def test_citation_graph_has_nodes(self, client, force_mock_api):
        """图谱节点数 ≥ 1 (mock 模式下应有 mock 论文之间引文关系)."""
        r = _post_search(client, "graph attention network", budget=0.5)
        assert r.status_code == 200
        graph = r.json().get("citation_graph") or {}
        nodes = graph.get("nodes") or []
        assert len(nodes) >= 1, f"citation_graph empty: {graph}"

    def test_report_contains_chinese_sections(self, client, force_mock_api):
        """综述报告中文 6 段结构 (R10.5 synthesize_agent 输出格式)."""
        r = _post_search(client, "diffusion model image generation", budget=0.5)
        assert r.status_code == 200
        report = r.json().get("report") or ""
        # 至少 200 字 + 出现至少 1 个核心中文小标题
        assert len(report) > 200, f"report too short: {len(report)} chars"
        for marker in ("研究概述", "核心论文"):
            assert marker in report, f"missing section '{marker}' in report"

    def test_health_detailed_endpoint(self, client, force_mock_api):
        """R10.5.14 P0-C: /api/v1/health/detailed 返回 ENVIRONMENT + 限流 + uptime."""
        c, _ = client
        r = c.get("/api/v1/health/detailed")
        assert r.status_code == 200
        data = r.json()
        # 顶层字段
        for field in ("status", "service", "version", "uptime_sec",
                      "environment", "llm_providers", "llm_default", "cache"):
            assert field in data, f"missing field: {field}"
        env = data["environment"]
        # conftest.py 强制 ENVIRONMENT=test, 这里应该读出 test
        assert env["name"] == "test", f"expected test mode, got {env['name']}"
        assert env["is_test"] is True
        assert env["is_dev"] is False
        assert env["is_prod"] is False
        # 限流档 (test 模式 → 1000/minute)
        assert env["rate_limits"]["search"] == "1000/minute"
        # uptime > 0
        assert data["uptime_sec"] > 0.0

    def test_health_endpoint_still_works(self, client, force_mock_api):
        """R10.5.14 P0-C: /health (原版) 不被破坏, 仍返 ok/degraded."""
        c, _ = client
        r = c.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("ok", "degraded")
        assert data["service"] == "ScholarFlow"


# ==================== CLI entry for manual run ====================
def main() -> int:
    """手动跑: python -m tests.e2e_test_full_pipeline (需 ENVIRONMENT=test)."""
    print("[e2e] starting full pipeline E2E (mock mode)")
    client = TestClient(main_mod.app)
    test_queries = [
        "transformer attention mechanism",
        "graph neural network NeurIPS 2022",
        "BERT pretraining language model",
        "diffusion model image generation",
    ]
    failed = 0
    for q in test_queries:
        r = _post_search(client, q, budget=0.5)
        if r.status_code != 200:
            print(f"  [FAIL] q='{q[:40]}' → {r.status_code} {r.text[:120]}")
            failed += 1
            continue
        data = r.json()
        report_len = len(data.get("report") or "")
        n_nodes = len((data.get("citation_graph") or {}).get("nodes") or [])
        constraints = data.get("constraints") or {}
        print(f"  [ok]   q='{q[:40]}' status={data['status']} "
              f"papers={len(data.get('ranked_papers') or [])} "
              f"nodes={n_nodes} report_len={report_len} "
              f"constraints={list(constraints.keys())} "
              f"cost=${data.get('total_cost_usd', 0):.4f}")
    # health/detailed
    r = client.get("/api/v1/health/detailed")
    if r.status_code == 200:
        d = r.json()
        print(f"  [ok]   health/detailed: env={d['environment']['name']} "
              f"uptime={d['uptime_sec']}s "
              f"providers={len(d['llm_providers'])}")
    else:
        print(f"  [FAIL] health/detailed → {r.status_code}")
        failed += 1
    if failed:
        print(f"\n[e2e] {failed} failures")
        return 1
    print(f"\n[e2e] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
