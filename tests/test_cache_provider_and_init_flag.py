"""cache.py P1 修复测试：(1) cache_key 加 provider 维度 (2) _init_db_once 标志位。

旧 bug:
  - cache_key 不含 provider → 跨 LLM provider 同 query 缓存污染（kimi 搜的
    结果被 glm 误命中）。
  - 每次 get_cached / set_cached / get_cached_async / set_cached_async 都跑
    _init_db() 做 schema 检查（~2-5ms 开销），/search 高频调用下浪费可观。

修复:
  - cache_key 增加 provider 参数（默认 None → "default"）。
  - 引入 _init_db_once() 用 _DB_INITIALIZED 模块级 bool 守卫，仅首次跑
    _init_db()。
  - get_cached / set_cached / get_cached_async / set_cached_async 都接受
    provider: str | None = None（向后兼容），签名变化不影响未传 provider
    的旧调用方。
"""
import asyncio
import sqlite3

import pytest

from backend.utils import cache as cache_mod


# ===== Fixtures =====

@pytest.fixture
def temp_cache_db(monkeypatch, tmp_path):
    """隔离 cache DB 到 temp 文件，避免污染真实数据。"""
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir(exist_ok=True)
    db_path = cache_dir / "test_search_cache.sqlite"

    monkeypatch.setattr(cache_mod, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    # 重置模块级 init 标志
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    return db_path


# ===== 1) cache_key 加 provider 维度 =====

def test_cache_key_includes_provider():
    """不同 provider 应生成不同 cache key。"""
    k1 = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    k2 = cache_mod.cache_key("q", 3, 1.0, provider="glm")
    k3 = cache_mod.cache_key("q", 3, 1.0, provider="anthropic")
    assert k1 != k2 != k3 != k1, "不同 provider 必须生成不同 key"


def test_cache_key_provider_none_default():
    """provider=None 与 provider="default" 应等价。"""
    k_none = cache_mod.cache_key("q", 3, 1.0, provider=None)
    k_default = cache_mod.cache_key("q", 3, 1.0, provider="default")
    assert k_none == k_default, "provider=None 应等同于 provider='default'"


def test_cache_key_provider_distinguishes_identical_query():
    """同 query 在不同 provider 下 key 不同（防跨 provider 污染）。"""
    k_kimi = cache_mod.cache_key("transformer attention", 3, 1.0, provider="kimi")
    k_glm = cache_mod.cache_key("transformer attention", 3, 1.0, provider="glm")
    assert k_kimi != k_glm


def test_cache_key_provider_backward_compat():
    """不传 provider（位置参数兼容旧调用）也能正常工作。"""
    # 旧调用：cache_key("q", 3, 1.0) — 仅 3 个位置参数
    k = cache_mod.cache_key("q", 3, 1.0)
    # 新调用：cache_key("q", 3, 1.0, provider=None)
    k_explicit = cache_mod.cache_key("q", 3, 1.0, provider=None)
    assert k == k_explicit, "不传 provider 应等同于 provider=None"


def test_cache_key_provider_changes_value_not_other_dimensions():
    """只有 provider 维度变化时 key 变化；其他维度不变时 key 稳定。"""
    k1 = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    k2 = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    assert k1 == k2, "同 provider 同 query 应生成稳定 key"


# ===== 2) _init_db_once 标志位 =====

def test_init_db_once_runs_only_first_time(temp_cache_db, monkeypatch):
    """_init_db_once 第二次调用时 _init_db 不会再被触发。"""
    call_count = [0]
    original_init_db = cache_mod._init_db

    def counting_init_db():
        call_count[0] += 1
        return original_init_db()

    monkeypatch.setattr(cache_mod, "_init_db", counting_init_db)
    # 重要：必须重置标志位（fixture 已做）
    assert cache_mod._DB_INITIALIZED is False

    cache_mod._init_db_once()
    assert call_count[0] == 1
    assert cache_mod._DB_INITIALIZED is True

    cache_mod._init_db_once()
    cache_mod._init_db_once()
    cache_mod._init_db_once()
    # 后续调用不应再触发 _init_db
    assert call_count[0] == 1, f"_init_db 被重复调用 {call_count[0]} 次（应有 1 次）"
    assert cache_mod._DB_INITIALIZED is True


def test_init_db_once_actually_creates_table(temp_cache_db):
    """首次 _init_db_once 必须真正创建 search_cache 表。"""
    assert cache_mod._DB_INITIALIZED is False
    cache_mod._init_db_once()

    # 表存在
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


# ===== 3) provider 参数端到端（set + get）=====

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

    # 读 kimi 应得 kimi 的响应
    got_kimi = cache_mod.get_cached("q", 3, 1.0, provider="kimi")
    assert got_kimi is not None
    assert got_kimi[0] == response_kimi

    # 读 glm 应得 glm 的响应
    got_glm = cache_mod.get_cached("q", 3, 1.0, provider="glm")
    assert got_glm is not None
    assert got_glm[0] == response_glm

    # 关键：两者内容不同
    assert got_kimi[0] != got_glm[0]


def test_provider_none_does_not_hit_provider_specific(temp_cache_db):
    """provider=None 应与 provider="kimi" 视为不同 key（避免污染）。"""
    response = {"report": "kimi", "ranked_papers": []}
    cache_mod.set_cached("q", 3, 1.0, response, 0.1, 10, provider="kimi")

    # provider=None 不应命中 kimi 的 cache
    got = cache_mod.get_cached("q", 3, 1.0, provider=None)
    assert got is None


# ===== 4) async 变体支持 provider =====

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
