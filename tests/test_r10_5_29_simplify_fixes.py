"""R10.5.29 (simplify 修复验证): 8 项 cleanup + 真实 bug 修复.

对应 /simplify Phase 2 验证后保留的 finding, 修过, 这里加 8 项防回归.

修复列表:
  E1  semantic_cache.py:205 set_semantic_cached 加 runtime_mode, LRU key
      改成 (mode, query) 避免跨模式污染
  E2  useSearch.ts: dispatchEvent 改 switch (5 cases)
  E3  useSearch.ts: 抽 isArrayOf<T> 泛型, 删 isStringArray / isRecentEntryArray
      的 inline 重复
  E4  useSearch.ts: 抽 isRecentEntry 单元素 validator
  E5  api.ts: 加 _cachedKey module-scope 缓存, 避免每次 fetch 读 storage
  E6  api.ts: setApiKey 同步 _cachedKey; _resetIdleTimer 同步清 cache
  E7  local_papers_db.py: _append_demo_marker 快路径 (无 ? # 时 f-string)
  E8  components/FilterPanel.tsx: 删死代码 (454 行, 0 importer)
  R1  QueryPanel: RecentEntry / RuntimeMode 改 import 不用 inline
  R2  models.py: SearchResponse runtime_mode 实际只走 2-state
      (real | mock) ; 'unknown' 留 default 缓存 fallback. 本测试不验
      行为只验字段存在.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ===== E1: semantic_cache 加 runtime_mode =====
def test_semantic_cache_lru_key_includes_runtime_mode():
    """E1 修复: _shingle_lru_put 接收 runtime_mode 并拼进 LRU key.
    旧版只按 query 拼 key, 'real' 模式写入的 'transformer attention' 会被
    'mock' 模式 'transformer attention mechanism' 命中 (跨污染)."""
    src = (ROOT / "backend" / "utils" / "semantic_cache.py").read_text(encoding="utf-8")
    # _shingle_lru_put 必须有 runtime_mode kwarg
    assert "def _shingle_lru_put(\n    query: str,\n    response_json: str,\n    cost: float,\n    tokens: int,\n    runtime_mode: str = \"unknown\"" in src, (
        "_shingle_lru_put 缺 runtime_mode 参数 (R10.5.29 simplify E1)"
    )
    # composite_key 必须用 runtime_mode 前缀
    assert "composite_key = f\"{runtime_mode}" in src, (
        "composite_key 缺 runtime_mode 前缀 (跨模式污染修复)"
    )
    # set_semantic_cached 必须接收 + 传 runtime_mode
    assert "async def set_semantic_cached(\n" in src
    # 在 set_semantic_cached 体内, _shingle_lru_put 调用必须传 runtime_mode=
    set_idx = src.find("async def set_semantic_cached(")
    window = src[set_idx:set_idx + 2000]
    assert "runtime_mode=runtime_mode" in window, (
        "set_semantic_cached 没把 runtime_mode 透传给 _shingle_lru_put"
    )


# ===== E2: useSearch dispatchEvent 改 switch =====
def test_use_search_dispatch_event_uses_switch():
    """E2 修复: 5 个 if (payload.event === 'X') 链 → switch. 验证源码里
    没有 5 个 'payload.event ===' 连续 if, 而是有 5 个 case."""
    src = (ROOT / "frontend" / "src" / "hooks" / "useSearch.ts").read_text(encoding="utf-8")
    # 5 个 case 必须在 dispatchEvent 函数体内
    dispatch_idx = src.find("const dispatchEvent = (payload: SSEEvent): boolean => {")
    assert dispatch_idx > 0
    # 截取到 dispatchEvent 函数结束 (~ 5 case 占 100 行)
    window = src[dispatch_idx:dispatch_idx + 4000]
    # 5 case 名称: started / node_complete / graph_snapshot / done / error / budget_exceeded
    expected_cases = [
        "case 'started':",
        "case 'node_complete':",
        "case 'graph_snapshot':",
        "case 'done':",
        "case 'error':",
        "case 'budget_exceeded':",
    ]
    for c in expected_cases:
        assert c in window, f"dispatchEvent switch 缺 {c!r} (R10.5.29 simplify E2)"
    # 旧版 5 个 if 不应再出现
    assert "if (payload.event === " not in window, (
        "dispatchEvent 仍有 5 个 if/else 链, 改 switch 没生效"
    )


# ===== E3: isArrayOf 泛型抽取 =====
def test_use_search_has_is_array_of_generic():
    """E3 修复: 抽 isArrayOf<T> 泛型, isStringArray + isRecentEntryArray 都用."""
    src = (ROOT / "frontend" / "src" / "hooks" / "useSearch.ts").read_text(encoding="utf-8")
    assert "const isArrayOf = <T>" in src, (
        "useSearch.ts 缺 isArrayOf<T> 泛型 (R10.5.29 simplify E3)"
    )
    # isStringArray 必须用 isArrayOf 实现
    assert "isArrayOf(v, (x): x is string =>" in src, (
        "isStringArray 没复用 isArrayOf"
    )
    # isRecentEntryArray 也用
    assert "isArrayOf(v, isRecentEntry)" in src, (
        "isRecentEntryArray 没复用 isArrayOf"
    )


# ===== E4: isRecentEntry 单元素 validator =====
def test_use_search_has_is_recent_entry_validator():
    """E4 修复: 抽 isRecentEntry 单元素 validator, 之前 isRecentEntryArray
    inline 一长串条件."""
    src = (ROOT / "frontend" / "src" / "hooks" / "useSearch.ts").read_text(encoding="utf-8")
    assert "function isRecentEntry(v: unknown): v is RecentEntry" in src, (
        "useSearch.ts 缺 isRecentEntry 单元素 validator (R10.5.29 simplify E4)"
    )


# ===== E5 + E6: api.ts _cachedKey 缓存 =====
def test_api_ts_has_cached_key_module_scope():
    """E5 修复: _cachedKey module-scope 缓存, 高频 fetch 避免重复 sessionStorage 读.
    E6 修复: setApiKey 同步 _cachedKey; _resetIdleTimer timeout 同步清 cache."""
    src = (ROOT / "frontend" / "src" / "services" / "api.ts").read_text(encoding="utf-8")
    assert "let _cachedKey: string | null | undefined = undefined" in src, (
        "api.ts 缺 _cachedKey module-scope 缓存 (R10.5.29 simplify E5)"
    )
    # setApiKey 头一行同步 cache
    set_idx = src.find("export function setApiKey(key: string | null): void {")
    set_window = src[set_idx:set_idx + 600]
    assert "_cachedKey = key" in set_window, (
        "setApiKey 没同步 _cachedKey (R10.5.29 simplify E6)"
    )
    # _resetIdleTimer timeout 同步 _cachedKey = null
    reset_idx = src.find("function _resetIdleTimer(): void {")
    reset_window = src[reset_idx:reset_idx + 600]
    assert "_cachedKey = null" in reset_window, (
        "_resetIdleTimer timeout 没同步 _cachedKey (R10.5.29 simplify E6)"
    )


# ===== E7: local_papers_db 快路径 =====
def test_local_papers_db_append_demo_marker_has_fast_path():
    """E7 修复: _append_demo_marker 在无 ? / # 时直接 f-string 拼, 避免每次
    urlparse 4 个 stdlib 调用. 50 篇论文 × 4 调用 = 200 stdlib 调用/响应."""
    from backend.api.local_papers_db import _append_demo_marker
    # 快路径触发
    assert _append_demo_marker("https://arxiv.org/abs/1234") == "https://arxiv.org/abs/1234?demo=1"
    # 慢路径 (有 ? 或 #) 仍用 urlparse
    assert _append_demo_marker("https://x.com/foo?q=1") == "https://x.com/foo?q=1&demo=1"
    assert _append_demo_marker("https://x.com/foo#sec") == "https://x.com/foo?demo=1#sec"


# ===== E8: FilterPanel.tsx 已删 =====
def test_filter_panel_file_deleted():
    """E8 修复: FilterPanel.tsx 死代码删除. R10.5.30 重新需要时再写."""
    fp = ROOT / "frontend" / "src" / "components" / "FilterPanel.tsx"
    assert not fp.exists(), "FilterPanel.tsx 死代码应该已删 (R10.5.29 simplify E8)"


# ===== R1: QueryPanel RecentEntry / RuntimeMode import =====
def test_query_panel_imports_recent_entry_and_runtime_mode():
    """R1 修复: QueryPanel 不再 inline RecentEntry / RuntimeMode 类型, 改 import."""
    src = (ROOT / "frontend" / "src" / "components" / "QueryPanel.tsx").read_text(encoding="utf-8")
    assert "import type { RecentEntry } from '../hooks/useSearch'" in src, (
        "QueryPanel 缺 RecentEntry import (R10.5.29 simplify R1)"
    )
    assert "type RuntimeMode } from '../services/api'" in src, (
        "QueryPanel 缺 RuntimeMode import (R10.5.29 simplify R1)"
    )
    # 不再有 inline 联合类型
    assert "Array<{ query: string; source: 'local' | 'real' | 'unknown'" not in src, (
        "QueryPanel 仍有 inline RecentEntry 类型"
    )
    assert "runtimeMode?: 'mock' | 'real'" not in src, (
        "QueryPanel 仍有 inline RuntimeMode 类型"
    )
