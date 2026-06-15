"""R10.5.29 (code-review 修复验证): 6 项审计发现 + 修复.

对应 Phase 2 验证后保留的 ≤10 个最高严重度 finding, 全部修过, 这里加 6 个
针对性测试防回归.

修复的 finding 列表:
  #1  search.py:180 set_cached_async 缺 runtime_mode (跨污染)
  #2  main.py:947 SSE node_complete 缺 cost_usd + tokens (CockpitDashboard 永远 $0)
  #3  main.py: 缺 graph_snapshot (EvolutionSlider 永不显示)
  #4  api.ts: 30 分钟 timer 不在 API 调用时重置 (用户活跃被登出)
  #5  useSearch.ts:130 migration 失败会 wipe data
  #6  _is_mock_response 内嵌 import + 包装
  #7  App.tsx ? 快捷键 + useCommandPalette Cmd+K 冲突
  #8  local_papers_db.py URL #fragment 拼接错
  #9  App.tsx FilterPanel 死 import
  #10 useSearch.ts:417 stopFallback 漏清 retry timer
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ===== #1: search.py:180 set_cached_async 必须传 runtime_mode =====
def test_search_py_set_cached_async_passes_runtime_mode():
    """/api/v1/search (search.py) 的 set_cached_async 调用必须传 runtime_mode=,
    避免 mock/real 跨污染."""
    src = (ROOT / "backend" / "api" / "routes" / "search.py").read_text(encoding="utf-8")
    # 必须 import get_runtime_mode
    assert "from backend.utils.runtime_mode import get_runtime_mode" in src, (
        "search.py 缺 get_runtime_mode import (R10.5.29 修复)"
    )
    # 必须在 set_cached_async 调用里传 runtime_mode=
    # 找 set_cached_async 块, 检查 runtime_mode= 在它之后出现
    idx = src.find("set_cached_async(")
    assert idx > 0
    # 找下一个 1000 字符内
    window = src[idx:idx + 1500]
    assert "runtime_mode=get_runtime_mode()" in window, (
        "search.py set_cached_async 缺 runtime_mode=get_runtime_mode() kwarg "
        "(R10.5.29 code-review #1)"
    )


# ===== #2: main.py SSE node_complete 必须带 cost_usd + tokens =====
def test_main_py_node_complete_emits_cost_and_tokens():
    """main.py 的 SSE node_complete 事件必须发 cost_usd + tokens,
    否则 CockpitDashboard 永远 $0 (R10.5.29 code-review #2)."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    # 找 node_complete 块, 检查紧跟的 yield _sse_format 字典
    idx = src.find('"event": "node_complete"')
    assert idx > 0
    window = src[idx:idx + 1200]
    assert '"cost_usd"' in window, "main.py node_complete 缺 cost_usd (R10.5.29 #2)"
    assert '"tokens"' in window, "main.py node_complete 缺 tokens (R10.5.29 #2)"


# ===== #3: main.py SSE 必须发 graph_snapshot (build_graph 节点后) =====
def test_main_py_emits_graph_snapshot_on_build_graph():
    """main.py 在 build_graph 节点完成后必须推 graph_snapshot,
    否则 EvolutionSlider 永不显示 (R10.5.29 code-review #3)."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert '"event": "graph_snapshot"' in src, (
        "main.py 缺 graph_snapshot SSE 事件 (R10.5.29 #3)"
    )
    # 必须在 build_graph 节点块内
    bg_idx = src.find('node_name == "build_graph"')
    assert bg_idx > 0
    window = src[bg_idx:bg_idx + 1500]
    assert '"event": "graph_snapshot"' in window, (
        "graph_snapshot 必须在 build_graph 节点条件块内"
    )


# ===== #8: local_papers_db URL 拼接不破坏 fragment =====
def test_local_papers_db_url_preserves_fragment():
    """#8 修复: URL 含 #fragment 时, ?demo=1 必须拼在 fragment 前.
    旧版 'https://x.com/foo#sec' 会被改成 'https://x.com/foo#sec?demo=1'
    (fragment 吃掉 query)."""
    from backend.api.local_papers_db import _append_demo_marker
    # Case 1: 无 query 无 fragment
    assert _append_demo_marker("https://x.com/foo") == "https://x.com/foo?demo=1"
    # Case 2: 有 query
    assert _append_demo_marker("https://x.com/foo?a=1") == "https://x.com/foo?a=1&demo=1"
    # Case 3: 有 fragment (核心修复)
    assert _append_demo_marker("https://x.com/foo#sec") == "https://x.com/foo?demo=1#sec"
    # Case 4: 都有
    assert (
        _append_demo_marker("https://x.com/foo?a=1#sec")
        == "https://x.com/foo?a=1&demo=1#sec"
    )


# ===== #6: _is_mock_response 包装已删 =====
def test_models_py_no_is_mock_response_wrapper():
    """#6 修复: _is_mock_response 包装层已删, 改用 top-level is_runtime_mock.
    行为更直接, 减少内嵌 import."""
    src = (ROOT / "backend" / "api" / "routes" / "models.py").read_text(encoding="utf-8")
    assert "def _is_mock_response" not in src, (
        "models.py 仍残留 _is_mock_response 包装 (R10.5.29 #6)"
    )
    # 必须 top-level import is_runtime_mock
    assert "from backend.utils.runtime_mode import is_runtime_mock" in src, (
        "models.py 缺 top-level is_runtime_mock import"
    )
    # 调用点直接用 is_runtime_mock()
    assert "if is_runtime_mock()" in src, "models.py 缺 is_runtime_mock() 直接调用"


# ===== #9: App.tsx 已删 FilterPanel 死 import =====
def test_app_tsx_no_dead_filter_panel_import():
    """#9 修复: FilterPanel 暂未挂载, 删死 import 避免误导."""
    src = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    # 不能再有 import { FilterPanel }
    assert "import { FilterPanel }" not in src, (
        "App.tsx 仍 import FilterPanel 但未挂载 (R10.5.29 #9)"
    )
    # 也不能 mount <FilterPanel ...>
    assert "<FilterPanel" not in src, "App.tsx 不应 mount FilterPanel"
