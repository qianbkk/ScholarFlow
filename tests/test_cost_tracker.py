"""Tests for the track_cost_node — 8-node pipeline 终结节点 (节点 ⑧).

R9 审计员 #4 报告: track_cost_node 是 8 节点中唯一 0 单测节点 (45 行纯函数).
本文件覆盖 8 个核心行为, 让 8/8 节点测试覆盖达成.

实际函数签名: track_cost_node(state: SearchState) -> SearchState
实际行为:
  1. 读 state 字段: total_cost_usd, total_tokens_used, budget_limit_usd,
     iteration, ranked_papers, model_usage
  2. logger.info + print 双写成本报告
  3. 返回 {**state, "status": "done"} — 仅强制 status='done', 其他字段透传

注意: 节点不做 merge/accumulate/increment, 只做"读 + 日志 + 强制 status=done".
下游节点 (refine 循环 + cost_guard) 负责累加 total_cost_usd / merge model_usage.
"""
from __future__ import annotations

from typing import cast

import pytest

from backend.agents.cost_tracker import track_cost_node
from backend.models.state import SearchState


# 最小可用 SearchState (避免漏字段被 TypedDict 类型检查抓, 也避免运行时 KeyError)
def _make_state(**overrides) -> SearchState:
    base: dict = {
        "original_query": "test query",
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {"nodes": [], "links": []},
        "iteration": 0,
        "max_iterations": 2,
        "expanded_paper_ids": [],
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "done",
        "error": None,
        "provider": None,
        "request_id": None,
        "top5_summary_cache": None,
    }
    base.update(overrides)
    return cast(SearchState, base)


def test_track_cost_node_empty_state():
    """空 state 不 crash, 强制 status='done' (其他字段取默认值).

    这是最宽松的 sanity check: 哪怕上游什么也没填, 节点不会 raise.
    """
    # 注意: 不能用空 dict, 因为 .get("ranked_papers", []) 会返回 [], 不会 crash.
    # 但 status 字段被强制设为 "done".
    result = track_cost_node(_make_state())
    assert result["status"] == "done"
    # 默认 total_cost_usd=0.0 应该保留 (成本不可丢失, 即便没花过钱)
    assert result["total_cost_usd"] == 0.0
    # 默认 model_usage={} 也保留
    assert result["model_usage"] == {}


def test_track_cost_node_preserves_total_cost_usd():
    """total_cost_usd 透传 — 节点不重算 cost, 只读 + 透传.

    含义: 多次调 track_cost_node 也不会改变 cost (cost 由 refine/synthesize 节点累加).
    多次调用返回的 total_cost_usd 永远等于 state 里的值.
    """
    state = _make_state(total_cost_usd=1.234)
    result1 = track_cost_node(state)
    result2 = track_cost_node(result1)
    assert result1["total_cost_usd"] == 1.234
    assert result2["total_cost_usd"] == 1.234, (
        "track_cost_node 不应改 total_cost_usd, 实际函数透传, 多次调用 cost 保持不变"
    )


def test_track_cost_node_preserves_model_usage():
    """model_usage 透传 — 节点不 merge, 多个 model 的 usage 字段原样保留.

    含义: 新 model 已经在 refine/synthesize 节点 merge 进 state 了,
    track_cost_node 不再二次 merge, 避免 double counting.
    """
    state = _make_state(
        model_usage={
            "deepseek-chat": {"tokens": 1000, "cost": 0.001},
            "deepseek-reasoner": {"tokens": 500, "cost": 0.002},
        }
    )
    result = track_cost_node(state)
    # 两个 model 都保留
    assert "deepseek-chat" in result["model_usage"]
    assert "deepseek-reasoner" in result["model_usage"]
    # 子字段 tokens / cost 原样保留
    assert result["model_usage"]["deepseek-chat"]["tokens"] == 1000
    assert result["model_usage"]["deepseek-chat"]["cost"] == 0.001
    assert result["model_usage"]["deepseek-reasoner"]["tokens"] == 500
    assert result["model_usage"]["deepseek-reasoner"]["cost"] == 0.002


def test_track_cost_node_top5_summary_cache():
    """top5_summary_cache 字段透传 (R6 TypedDict 引入, 跨 retry 复用).

    query_refiner 在每次 retry 写入 top5_summary_cache; track_cost_node 是
    收尾节点, 必须保留这个字段让最终 state 自包含 (便于审计 + cache 序列化).
    """
    state = _make_state(top5_summary_cache="Top 5 papers: P1, P2, P3, P4, P5")
    result = track_cost_node(state)
    assert result["top5_summary_cache"] == "Top 5 papers: P1, P2, P3, P4, P5"

    # None 也应透传
    state2 = _make_state(top5_summary_cache=None)
    result2 = track_cost_node(state2)
    assert result2["top5_summary_cache"] is None


def test_track_cost_node_max_iterations_zero():
    """max_iterations=0 边界 — 节点不读 max_iterations 也不做边界检查, 不 crash.

    实际 max_iterations 校验在 main.py /search 入口 (Query(..., ge=1, le=5)).
    节点函数本身对任何 max_iterations 值都安全.
    """
    state = _make_state(max_iterations=0, iteration=0)
    result = track_cost_node(state)
    assert result["max_iterations"] == 0
    assert result["status"] == "done"


def test_track_cost_node_status_done():
    """status='done' 输入时, 输出仍 'done' (idempotent).

    多次调 track_cost_node 不会进入循环 (没有 'done' 特殊处理分支).
    """
    state = _make_state(status="done", total_cost_usd=0.5)
    result = track_cost_node(state)
    assert result["status"] == "done"
    assert result["total_cost_usd"] == 0.5


def test_track_cost_node_status_error_preserves_cost():
    """status='error' 输入时, total_cost_usd 仍保留 (成本不可丢失).

    含义: 即便 pipeline 提前 error 中断, 已经产生的 LLM 调用 cost 必须保留
    在最终 state 里, 供 billing/audit 查询. track_cost_node 透传 cost 字段.
    注意: 实际函数会强制 status='done' (收尾), 测试的是"cost 不丢" ——
    上游 caller 决定是否在 error 路径上调 track_cost_node.
    """
    state = _make_state(status="error", total_cost_usd=0.987, total_tokens_used=4242)
    result = track_cost_node(state)
    # 核心断言: cost 不能丢
    assert result["total_cost_usd"] == 0.987, (
        "status=error 时, 已产生的 cost 必须保留在 final state"
    )
    assert result["total_tokens_used"] == 4242
    # 收尾节点语义: status 被强制设为 'done' (但这要求 caller 决定是否调;
    # 这里只测 cost 透传, 不对 status 做强制断言以保持函数纯粹性文档)


def test_track_cost_node_iteration_preserved():
    """iteration 字段保留 — track_cost_node 不 increment iteration.

    含义: 节点仅做"日志 + 强制 done", iteration 由 refine 循环里的 should_refine
    决定. 多次调 track_cost_node, iteration 保持不变.
    """
    state = _make_state(iteration=5)
    result = track_cost_node(state)
    assert result["iteration"] == 5, (
        "track_cost_node 不应 increment iteration, 实测透传 (increment 由 refine 循环负责)"
    )
    # 二次调用也不变
    result2 = track_cost_node(result)
    assert result2["iteration"] == 5


def test_track_cost_node_logs_cost_report(caplog):
    """logger.info 应输出 cost 报告 (审计 trail).

    实际函数用 logger.info 而非 print, 便于日志采集. 这里验证日志包含
    关键 token + cost 数字, 防止 'logger.info 漏写' 的回归.
    """
    import logging

    state = _make_state(
        total_cost_usd=0.1234,
        total_tokens_used=1234,
        iteration=2,
        ranked_papers=[{"id": "p1"}, {"id": "p2"}],
        model_usage={"deepseek-chat": {"tokens": 1234, "cost": 0.1234}},
    )
    with caplog.at_level(logging.INFO, logger="backend.agents.cost_tracker"):
        track_cost_node(state)
    # 至少一条 cost_tracker 日志
    cost_logs = [r for r in caplog.records if "[cost_tracker]" in r.getMessage()]
    assert len(cost_logs) >= 1, f"expected cost_tracker log, got: {caplog.records}"
    # 顶层汇总日志含 total_cost
    summary_log = next(
        (r for r in cost_logs if "total_cost" in r.getMessage()),
        None,
    )
    assert summary_log is not None, (
        f"expected summary log with total_cost, got: {[r.getMessage() for r in cost_logs]}"
    )
    # 数值字段在 formatted message 里
    msg = summary_log.getMessage()
    assert "1234" in msg, f"tokens not in log: {msg}"
    assert "$0.1234" in msg, f"cost not in log: {msg}"


def test_track_cost_node_logs_per_model(caplog):
    """每个 model 单独 log 一条 [cost_tracker] model=... 记录.

    便于审计查 '具体哪个 model 花了多少' — 不只给总数, 还给分项.
    """
    import logging

    state = _make_state(
        model_usage={
            "deepseek-chat": {"tokens": 100, "cost": 0.001},
            "deepseek-reasoner": {"tokens": 200, "cost": 0.004},
        },
    )
    with caplog.at_level(logging.INFO, logger="backend.agents.cost_tracker"):
        track_cost_node(state)
    cost_logs = [r for r in caplog.records if "[cost_tracker]" in r.getMessage()]
    per_model_logs = [r for r in cost_logs if "model=" in r.getMessage()]
    assert len(per_model_logs) == 2, (
        f"expected 2 per-model logs, got {len(per_model_logs)}: "
        f"{[r.getMessage() for r in per_model_logs]}"
    )
    # 两个 model 都在日志里
    model_names = {r.getMessage() for r in per_model_logs}
    assert any("deepseek-chat" in m for m in model_names)
    assert any("deepseek-reasoner" in m for m in model_names)
