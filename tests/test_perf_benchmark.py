"""
R10.5.15 (P1-B): 端到端性能基准测试.

P1-14 审计要求: 跟踪单次搜索的端到端延时 / 成本 / 论文数, 防止
R10.5.x 优化"效果飘" — 任何 commit 不能让 mock 模式平均耗时退化 >50%.

策略 (R10.5.7 audit 提的):
  - 跑 5 个不同复杂度 query, mock 模式 (LLM_MOCK + API_MOCK)
  - 记录: elapsed_seconds / total_cost_usd / papers 数 / nodes 数
  - 阈值 (CI 不会飘):
      * 单 query dev 模式 < 30s (R10.5.31 放宽为 60s, 8 节点 mock 流水线
        实测 30-60s 取决于论文数)
      * 全 5 query 总 < 90s (R10.5.31 放宽为 300s, 用户指示 mock 快速
        反应不必要, 把阈值调成 env-driven)
      * 论文数 ≥ 1 (mock 应有 fallback)
  - 输出: pytest 报告 + stdout 表格 (一行一 case)

R10.5.15 阈值来源:
  - dev 模式 30s: R10.5.7 实测 mock 平均 1-3s, 5-6s 留 5x buffer
  - 真实 LLM 120s: 留 1.5x R10.5.7 实测 ~84s
  - R10.5.31 (F3): 用户放宽阈值. 默认 60s/300s, env 覆盖:
      PERF_PER_QUERY_TIMEOUT=30 PERF_TOTAL_TIMEOUT=90 pytest
"""
import os
import time
import uuid
import statistics
import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod


# R10.5.31 (F3): env-driven 阈值, 默认放宽. 8 节点 mock 流水线实测
# 30-60s (R10.5.30 D4 加本地论文库后论文数 50+).
PERF_PER_QUERY_TIMEOUT = float(os.getenv("PERF_PER_QUERY_TIMEOUT", "60.0"))
PERF_TOTAL_TIMEOUT = float(os.getenv("PERF_TOTAL_TIMEOUT", "300.0"))


QUERY_BENCHMARKS = [
    ("simple", "transformer self-attention"),
    ("medium", "graph neural network molecular property"),
    ("complex", "AlphaFold protein structure prediction since 2022"),
    ("cross_domain", "federated learning privacy preserving"),
    ("trending", "large language model alignment RLHF"),
]


@pytest.fixture
def bench_client(monkeypatch, force_mock_api):
    """Benchmark 专用 client. 用唯一 query 前缀避免缓存命中."""
    yield TestClient(main_mod.app)


def _post(client, query, budget=0.5):
    unique = f" {uuid.uuid4().hex[:8]}"
    return client.post(
        "/api/v1/search",
        json={"query": query + unique, "budget": budget, "provider": "minimax"},
    )


class TestPerfBenchmark:
    """R10.5.15 (P1-B): 性能基准."""

    def test_per_query_latency_under_30s(self, bench_client):
        """每 query dev 模式 mock 跑 < PERF_PER_QUERY_TIMEOUT (R10.5.31 F3 默认 60s)."""
        timings = []
        for label, q in QUERY_BENCHMARKS:
            t0 = time.time()
            r = _post(bench_client, q)
            elapsed = time.time() - t0
            timings.append((label, elapsed, r.status_code))
            assert r.status_code == 200, f"{label} failed: {r.status_code}"
            assert elapsed < PERF_PER_QUERY_TIMEOUT, (
                f"{label} too slow: {elapsed:.1f}s "
                f"(>{PERF_PER_QUERY_TIMEOUT}s budget)"
            )
        # 输出表格
        print("\n=== Per-query latency (mock mode) ===")
        for label, el, code in timings:
            print(f"  {label:14s}: {el:6.2f}s  status={code}")
        avg = statistics.mean(t for _, t, _ in timings)
        print(f"  {'AVERAGE':14s}: {avg:6.2f}s")

    def test_total_budget_under_90s(self, bench_client):
        """5 个 query 总耗时 < PERF_TOTAL_TIMEOUT (R10.5.31 F3 默认 300s).
        防止某 commit 让 mock 模式慢 10x 还能 CI 绿."""
        t0 = time.time()
        for _, q in QUERY_BENCHMARKS:
            r = _post(bench_client, q)
            assert r.status_code == 200
        total = time.time() - t0
        assert total < PERF_TOTAL_TIMEOUT, (
            f"5-query total too slow: {total:.1f}s "
            f"(>{PERF_TOTAL_TIMEOUT}s budget)"
        )
        print(f"\n=== 5-query total: {total:.2f}s ===")

    def test_each_query_returns_papers(self, bench_client):
        """每个 query 都返至少 1 篇论文 (mock fallback 必须工作)."""
        for label, q in QUERY_BENCHMARKS:
            r = _post(bench_client, q)
            data = r.json()
            n = len(data.get("ranked_papers") or [])
            assert n >= 1, f"{label} got 0 papers"
        print("\n=== All 5 queries returned >=1 paper (mock fallback works) ===")

    def test_cost_reasonable_per_query(self, bench_client):
        """每次成本 < $0.10. mock 模式应接近 $0. 真实 LLM 单次 $0.05-0.30 留 buffer."""
        for label, q in QUERY_BENCHMARKS:
            r = _post(bench_client, q)
            data = r.json()
            cost = data.get("total_cost_usd") or 0
            assert cost < 0.10, f"{label} cost too high: ${cost:.4f}"
        print("\n=== All 5 queries < $0.10 (mock mode, expect ~$0) ===")

    def test_constraints_propagation(self, bench_client):
        """P0-A: 4 维约束 (venues/year_range/methods/datasets) 都能在 SearchResponse 看到."""
        for label, q in QUERY_BENCHMARKS:
            r = _post(bench_client, q)
            data = r.json()
            constraints = data.get("constraints") or {}
            assert isinstance(constraints, dict)
            # 4 维 schema 都在 (值可能 None)
            for key in ("venues", "year_range", "methods", "datasets"):
                assert key in constraints, f"{label} missing constraints.{key}"
        print("\n=== All 5 queries have 4-dim constraints schema ===")
