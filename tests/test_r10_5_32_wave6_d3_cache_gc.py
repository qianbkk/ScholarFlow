"""R10.5.32 (wave 6) cache GC + GraphPanel 静态契约测试.

覆盖:
  1. gc_cache: 删 30 天前条目
  2. gc_cache: 删超 1000 行最旧条目
  3. gc_cache: 空表返 0
  4. gc_cache: 表不存在 (init 之前) 返 0 不抛
  5. GraphPanel: 静态契约 — color 用 Viridis 色板 (色觉障碍友好)
  6. GraphPanel: 静态契约 — alphaDecay 0.08 (50+ 节点更快收敛)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_f6_gc_cache_deletes_old_entries():
    """gc_cache: created_at 30 天前的 entry 被删."""
    import backend.utils.cache as _cache
    orig_db = _cache._DB
    orig_init = _cache._DB_INITIALIZED
    try:
        import tempfile
        tmp_db = Path(tempfile.gettempdir()) / "sf_f6_gc_old_test.sqlite"
        if tmp_db.exists():
            tmp_db.unlink()
        _cache._DB = tmp_db
        _cache._DB_INITIALIZED = False
        _cache._init_db_once()

        # 插 1 条新 + 1 条 100 天前
        conn = _cache._connect_with_wal("cache")
        try:
            conn.execute(
                "INSERT INTO search_cache (query_hash, response_json, cost_usd, tokens, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("new_hash", "{}", 0.1, 100, time.time()),
            )
            conn.execute(
                "INSERT INTO search_cache (query_hash, response_json, cost_usd, tokens, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("old_hash", "{}", 0.1, 100, time.time() - 100 * 86400),
            )
            conn.commit()
        finally:
            conn.close()

        results = _cache.gc_cache(max_age_days=30, max_rows=1000)
        assert results["cache"] == 1, f"应删 1 条, 实际 {results['cache']}"

        # 验证 new_hash 还在, old_hash 没了
        conn = _cache._connect_with_wal("cache")
        try:
            rows = conn.execute("SELECT query_hash FROM search_cache").fetchall()
        finally:
            conn.close()
        assert ("new_hash",) in rows
        assert ("old_hash",) not in rows
    finally:
        _cache._DB = orig_db
        _cache._DB_INITIALIZED = orig_init


def test_f6_gc_cache_respects_row_cap():
    """gc_cache: 超 max_rows 限制时删最旧, 保留最新 max_rows 条."""
    import backend.utils.cache as _cache
    orig_db = _cache._DB
    orig_init = _cache._DB_INITIALIZED
    try:
        import tempfile
        tmp_db = Path(tempfile.gettempdir()) / "sf_f6_gc_cap_test.sqlite"
        if tmp_db.exists():
            tmp_db.unlink()
        _cache._DB = tmp_db
        _cache._DB_INITIALIZED = False
        _cache._init_db_once()

        # 插 5 条, created_at 递增
        conn = _cache._connect_with_wal("cache")
        try:
            now = time.time()
            for i in range(5):
                conn.execute(
                    "INSERT INTO search_cache (query_hash, response_json, cost_usd, tokens, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (f"hash_{i}", "{}", 0.1, 100, now + i),
                )
            conn.commit()
        finally:
            conn.close()

        # cap=3 应删最旧 2 条 (hash_0, hash_1)
        results = _cache.gc_cache(max_age_days=365, max_rows=3)
        assert results["cache"] == 2, f"cap=3 应删 2 条, 实际 {results['cache']}"

        conn = _cache._connect_with_wal("cache")
        try:
            rows = {r[0] for r in conn.execute("SELECT query_hash FROM search_cache").fetchall()}
        finally:
            conn.close()
        assert rows == {"hash_2", "hash_3", "hash_4"}
    finally:
        _cache._DB = orig_db
        _cache._DB_INITIALIZED = orig_init


def test_f6_gc_cache_empty_returns_zero():
    """gc_cache: 空表 (init 后没插任何数据) 返 0 不抛."""
    import backend.utils.cache as _cache
    orig_db = _cache._DB
    orig_init = _cache._DB_INITIALIZED
    try:
        import tempfile
        tmp_db = Path(tempfile.gettempdir()) / "sf_f6_gc_empty_test.sqlite"
        if tmp_db.exists():
            tmp_db.unlink()
        _cache._DB = tmp_db
        _cache._DB_INITIALIZED = False
        _cache._init_db_once()

        results = _cache.gc_cache()
        assert results["cache"] == 0
    finally:
        _cache._DB = orig_db
        _cache._DB_INITIALIZED = orig_init


def test_f6_graphpanel_uses_viridis_color_palette():
    """GraphPanel: 静态契约 — 节点颜色用 Viridis 色板 (色觉障碍友好)."""
    src_path = ROOT / "frontend" / "src" / "components" / "GraphPanel.tsx"
    src = src_path.read_text(encoding="utf-8")
    # Viridis 3-stop: #fde725 (黄) → #21918c (青) → #440154 (深紫)
    assert "#fde725" in src, "R10.5.32 (wave 6): GraphPanel 应使用 Viridis 色板起点 #fde725"
    assert "#440154" in src, "R10.5.32 (wave 6): GraphPanel 应使用 Viridis 色板终点 #440154"
    # 旧绿渐变 (色觉障碍不友好) 应该没了
    assert "'#ffffcc'" not in src, "R10.5.32 (wave 6): 旧 #ffffcc 绿渐变应已替换"
    assert "'#78c679'" not in src, "R10.5.32 (wave 6): 旧 #78c679 绿渐变应已替换"


def test_f6_graphpanel_uses_alpha_decay_008():
    """GraphPanel: 静态契约 — alphaDecay 0.08, 50+ 节点更快收敛."""
    src_path = ROOT / "frontend" / "src" / "components" / "GraphPanel.tsx"
    src = src_path.read_text(encoding="utf-8")
    assert ".alphaDecay(0.08)" in src, (
        "R10.5.32 (wave 6): alphaDecay 应为 0.08 (旧 0.05 在 50+ 节点慢)"
    )
