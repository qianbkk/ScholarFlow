"""R10.5.48 (P1) 测试: Conservative token pre-check + null result cache.

覆盖:
  Part A: Token estimator
    1. estimate_tokens("") == 0
    2. estimate_tokens("a") == 1 (向上取整)
    3. estimate_tokens("abcd") == 1
    4. estimate_tokens("abcdefgh") == 2
    5. estimate_request_cost 随 max_iter 增长
    6. pre_check_budget 接受 (cost <= budget)
    7. pre_check_budget 拒绝 (cost > budget) 抛 HTTPException 402
    8. pre_check_budget 跳过 user_budget <= 0 (OPEN_MODE)

  Part B: Null result cache
    9. _is_null_result: 空 ranked + 空 graph → True
   10. _is_null_result: 有 ranked → False
   11. _is_null_result: 有 graph nodes → False
   12. set_cached_async 空结果 → 写 null_cache (不写 search_cache)
   13. set_cached_async 非空结果 → 写 search_cache (不写 null_cache)
   14. get_cached_async 主缓存 miss + null_cache hit (5min 内) → 返空结果
   15. get_cached_async 主缓存 hit → 直接返 (不查 null_cache)
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ===== Part A: Token estimator =====

def test_estimate_tokens_empty():
    """[R10.5.48] estimate_tokens(空串) == 0."""
    from backend.utils.token_estimator import estimate_tokens
    assert estimate_tokens("") == 0


def test_estimate_tokens_single_char():
    """[R10.5.48] estimate_tokens("a") == 1 (向上取整)."""
    from backend.utils.token_estimator import estimate_tokens
    assert estimate_tokens("a") == 1


def test_estimate_tokens_exact_boundary():
    """[R10.5.48] 4 chars = 1 token, 5 chars = 2 tokens."""
    from backend.utils.token_estimator import estimate_tokens
    assert estimate_tokens("abcd") == 1  # (4+3)//4 = 1
    assert estimate_tokens("abcde") == 2  # (5+3)//4 = 2


def test_estimate_tokens_long_text():
    """[R10.5.48] 长文本按 chars/4 估算."""
    from backend.utils.token_estimator import estimate_tokens
    text = "a" * 1000
    assert estimate_tokens(text) == 250  # (1000+3)//4 = 250


def test_estimate_request_cost_scales_with_iter():
    """[R10.5.48] estimate_request_cost 随 max_iter 增长."""
    from backend.utils.token_estimator import estimate_request_cost

    cost_1 = estimate_request_cost(prompt_size_chars=100, max_iter=1)
    cost_3 = estimate_request_cost(prompt_size_chars=100, max_iter=3)
    cost_5 = estimate_request_cost(prompt_size_chars=100, max_iter=5)
    assert cost_3 > cost_1
    assert cost_5 > cost_3


def test_pre_check_budget_accepts_when_cost_within():
    """[R10.5.48] cost < budget 时不抛错."""
    from backend.utils.token_estimator import pre_check_budget

    # 大 budget, 小 prompt → 通过
    pre_check_budget(
        prompt_size_chars=100,
        user_budget=10.0,
        max_iter=3,
    )  # 不抛 = 通过


def test_pre_check_budget_rejects_402_when_over():
    """[R10.5.48] cost > budget 时抛 HTTPException(402)."""
    from fastapi import HTTPException
    from backend.utils.token_estimator import pre_check_budget

    # 大 prompt + 多次 iter + 极小 budget → 必拒
    with pytest.raises(HTTPException) as exc_info:
        pre_check_budget(
            prompt_size_chars=100_000,  # 100k chars
            user_budget=0.1,  # 极小 budget
            max_iter=5,  # 最大 iter
        )
    assert exc_info.value.status_code == 402
    assert "估算" in str(exc_info.value.detail) or "成本" in str(exc_info.value.detail)


def test_pre_check_budget_skips_when_unlimited():
    """[R10.5.48] user_budget <= 0 (OPEN_MODE / 无限) → 跳过检查."""
    from backend.utils.token_estimator import pre_check_budget

    # budget=0 → 跳过
    pre_check_budget(prompt_size_chars=100_000, user_budget=0.0, max_iter=5)
    pre_check_budget(prompt_size_chars=100_000, user_budget=-1.0, max_iter=5)
    # 都不抛 = 通过


# ===== Part B: Null result cache =====

@pytest.fixture
def _null_cache_db(monkeypatch, tmp_path):
    """每个测试用 tmp_path 隔离 cache DB."""
    from backend.utils import cache as cache_mod

    db_path = tmp_path / "test_null_cache.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    yield db_path


def test_is_null_result_empty_ranked_empty_graph():
    """[R10.5.48] _is_null_result: ranked=[] + graph 无 nodes → True."""
    from backend.utils.cache import _is_null_result

    assert _is_null_result({
        "ranked_papers": [],
        "citation_graph": {"nodes": [], "links": []},
    }) is True


def test_is_null_result_with_ranked_papers():
    """[R10.5.48] _is_null_result: 有 ranked_papers → False."""
    from backend.utils.cache import _is_null_result

    assert _is_null_result({
        "ranked_papers": [{"paper_id": "p1", "title": "T"}],
        "citation_graph": {},
    }) is False


def test_is_null_result_with_graph_nodes():
    """[R10.5.48] _is_null_result: 有 graph nodes (即使 ranked=[]) → False."""
    from backend.utils.cache import _is_null_result

    assert _is_null_result({
        "ranked_papers": [],
        "citation_graph": {"nodes": [{"id": "n1"}], "links": []},
    }) is False


def test_is_null_result_invalid_input():
    """[R10.5.48] _is_null_result: 非 dict 输入 → False (防御性)."""
    from backend.utils.cache import _is_null_result

    assert _is_null_result(None) is False
    assert _is_null_result("not a dict") is False
    assert _is_null_result(123) is False


@pytest.mark.asyncio
async def test_set_cached_async_null_result_goes_to_null_cache(_null_cache_db):
    """[R10.5.48] 空结果写 null_cache, 不写 search_cache."""
    import sqlite3
    from backend.utils import cache as cache_mod
    from backend.utils.cache import set_cached_async, get_cached_async, _init_db_once

    _init_db_once()

    # 写空结果
    null_response = {
        "report": "未检索到相关论文。",
        "ranked_papers": [],
        "citation_graph": {"nodes": [], "links": []},
    }
    await set_cached_async(
        query="cold query xyzzy",
        max_iterations=3,
        budget=2.0,
        response=null_response,
        cost_usd=0.05,
        tokens=100,
        provider="kimi",
    )

    # 验证: null_cache 有 1 行, search_cache 0 行
    conn = sqlite3.connect(str(_null_cache_db))
    try:
        null_count = conn.execute("SELECT COUNT(*) FROM null_cache").fetchone()[0]
        search_count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
    finally:
        conn.close()

    assert null_count == 1, f"Expected 1 row in null_cache, got {null_count}"
    assert search_count == 0, f"Expected 0 rows in search_cache, got {search_count}"


@pytest.mark.asyncio
async def test_set_cached_async_non_null_goes_to_search_cache(_null_cache_db):
    """[R10.5.48] 非空结果写 search_cache, 不写 null_cache."""
    import sqlite3
    from backend.utils import cache as cache_mod
    from backend.utils.cache import set_cached_async, _init_db_once

    _init_db_once()

    # 写非空结果
    non_null_response = {
        "report": "找到 5 篇相关论文",
        "ranked_papers": [
            {"paper_id": "p1", "title": "Paper 1", "abstract": "x" * 100}
        ],
        "citation_graph": {"nodes": [{"id": "n1"}], "links": []},
    }
    await set_cached_async(
        query="real query",
        max_iterations=3,
        budget=2.0,
        response=non_null_response,
        cost_usd=0.10,
        tokens=500,
        provider="kimi",
    )

    conn = sqlite3.connect(str(_null_cache_db))
    try:
        null_count = conn.execute("SELECT COUNT(*) FROM null_cache").fetchone()[0]
        search_count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
    finally:
        conn.close()

    assert search_count == 1, f"Expected 1 row in search_cache, got {search_count}"
    assert null_count == 0, f"Expected 0 rows in null_cache, got {null_count}"


@pytest.mark.asyncio
async def test_get_cached_async_finds_null_cache_on_main_miss(_null_cache_db):
    """[R10.5.48] 主缓存 miss + null_cache hit (5min 内) → 返空结果."""
    from backend.utils.cache import set_cached_async, get_cached_async, _init_db_once

    _init_db_once()

    null_response = {
        "report": "未检索到相关论文。",
        "ranked_papers": [],
        "citation_graph": {"nodes": [], "links": []},
    }
    await set_cached_async(
        query="xyzzy cold",
        max_iterations=3,
        budget=2.0,
        response=null_response,
        cost_usd=0.05,
        tokens=100,
        provider="kimi",
    )

    # get_cached_async 应该命中 null_cache
    result = await get_cached_async(
        query="xyzzy cold",
        max_iterations=3,
        budget=2.0,
        provider="kimi",
    )
    assert result is not None, "Should hit null_cache"
    cached_response, cost, tokens = result
    assert cached_response["report"] == "未检索到相关论文。"
    assert cost == 0.05
    assert tokens == 100


@pytest.mark.asyncio
async def test_get_cached_async_prefers_main_cache_over_null(_null_cache_db):
    """[R10.5.48] 主缓存 hit 优先 (不查 null_cache)."""
    from backend.utils.cache import set_cached_async, get_cached_async, _init_db_once

    _init_db_once()

    # 写主缓存
    non_null = {
        "report": "real result",
        "ranked_papers": [{"paper_id": "p1", "title": "T", "abstract": "x" * 100}],
        "citation_graph": {"nodes": [{"id": "n1"}], "links": []},
    }
    await set_cached_async(
        query="ambiguous query",
        max_iterations=3,
        budget=2.0,
        response=non_null,
        cost_usd=0.10,
        tokens=500,
        provider="kimi",
    )

    # 写 null_cache (同 key 应该会覆盖? 不同 key 是不同 row)
    # 实际上 cache_key 包含 query, 所以"ambiguous query"在两边都不会冲突
    # 这里只测主缓存能命中
    result = await get_cached_async(
        query="ambiguous query",
        max_iterations=3,
        budget=2.0,
        provider="kimi",
    )
    assert result is not None
    cached, _, _ = result
    assert cached["report"] == "real result"


@pytest.mark.asyncio
async def test_get_cached_async_null_cache_respects_5min_ttl(_null_cache_db):
    """[R10.5.48] null_cache 超过 5min TTL 自动失效."""
    import sqlite3
    from backend.utils.cache import set_cached_async, get_cached_async, _init_db_once, _connect_with_wal
    import time

    _init_db_once()

    null_response = {
        "report": "未检索到相关论文。",
        "ranked_papers": [],
        "citation_graph": {"nodes": [], "links": []},
    }
    await set_cached_async(
        query="ttl test",
        max_iterations=3,
        budget=2.0,
        response=null_response,
        cost_usd=0.05,
        tokens=100,
        provider="kimi",
    )

    # 模拟: 把 null_cache 的 created_at 改成 6 分钟前
    conn = _connect_with_wal()
    try:
        conn.execute(
            "UPDATE null_cache SET created_at=? WHERE query_hash IN (SELECT query_hash FROM null_cache)",
            (time.time() - 360,),  # 6 min ago
        )
        conn.commit()
    finally:
        conn.close()

    # get_cached_async 应该返 None (TTL 过期)
    result = await get_cached_async(
        query="ttl test",
        max_iterations=3,
        budget=2.0,
        provider="kimi",
    )
    assert result is None, (
        f"Null cache entry past 5min TTL should be invalidated, got {result}"
    )


@pytest.mark.asyncio
async def test_get_cached_async_cache_penetration_defense(_null_cache_db):
    """[R10.5.48] 集成: cache_penetration 防御 — 5 次相同空结果, 第 2-5 次
    走 null_cache, 不会触发后续 LLM 调用."""
    from backend.utils.cache import set_cached_async, get_cached_async, _init_db_once

    _init_db_once()

    null_response = {
        "report": "未检索到相关论文。",
        "ranked_papers": [],
        "citation_graph": {"nodes": [], "links": []},
    }

    # 第一次写
    await set_cached_async(
        query="spammed_query",
        max_iterations=3,
        budget=2.0,
        response=null_response,
        cost_usd=0.05,
        tokens=100,
        provider="kimi",
    )

    # 后续 4 次读, 应该都命中 null_cache
    for i in range(4):
        result = await get_cached_async(
            query="spammed_query",
            max_iterations=3,
            budget=2.0,
            provider="kimi",
        )
        assert result is not None, f"Iteration {i+2} should hit null_cache"
        cached, cost, _ = result
        assert cached["report"] == "未检索到相关论文。"
        # 关键: cost 是第一次的 cost, 不是新 cost
        assert cost == 0.05
