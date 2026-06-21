"""R10.5.30 (D4-D7) 综合防回归测试 — R10.5.59 重写版.

R10.5.54 frontend rebuild 把 12 文件合并重命名:
  - QueryPanel.tsx → SearchWorkspace.tsx + QueryInput.tsx + PaperList.tsx
  - GraphPanel.tsx → GraphPage.tsx (重命名)
  - useSearch.ts / useLocalStorage.ts / paperFilters.ts 整文件删除
    (逻辑内联到 useStore.ts)
  - SelectionContext.tsx → useStore (单 store + useSyncExternalStore)
  - paperFilters 类型 + DEFAULT_FILTERS 概念废弃, 改用 SearchSummary + useStore
  - ChangelogModal 数据结构从 {emoji:'X'} 改为 {version, date, summary, items}

测试保留 D4 (本地论文库),D6 (changelog + footer),D7 (storage keys)
3 个核心契约. D5 (QueryPanel 静态契约) 改为检查 PaperList 多选 props.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ===== D4: 本地论文库真接入 =====
def test_d4_openalex_search_papers_marks_source_local_demo():
    os.environ["API_MOCK"] = "true"
    os.environ["LLM_MOCK"] = "true"
    import importlib
    import backend.utils.runtime_mode
    importlib.reload(backend.utils.runtime_mode)
    import backend.api.openalex
    importlib.reload(backend.api.openalex)
    import asyncio
    papers = asyncio.run(backend.api.openalex.search_papers("transformer", limit=3))
    assert len(papers) >= 1
    for p in papers:
        assert p.source == "local_demo", (
            f"D4: paper.source 应 = 'local_demo', 实际 {p.source!r}"
        )


def test_d4_local_papers_db_url_has_demo_marker():
    """URL 含 demo=1 (跟 R10.5.29 #fragment 修复一致)."""
    from backend.api.local_papers_db import get_local_demo_papers
    papers = get_local_demo_papers(limit=3)
    for p in papers:
        if p.url:
            assert "demo=1" in p.url


# ===== D5: 多选接入 — R10.5.54 重构后改检查 PaperList.tsx =====
def test_d5_paper_list_supports_multi_select():
    """R10.5.54 重构后 PaperList 取代旧 QueryPanel 接受 selectedPaperIds props + shift-click 多选."""
    src = (ROOT / "frontend" / "src" / "components" / "PaperList.tsx").read_text(encoding="utf-8")
    # PaperList 接受 papers + onSelect 等 props
    assert "onSelect" in src or "selectPaper" in src, "PaperList 缺 onSelect / selectPaper"
    # useStore 提供 selectedPaperId / selectedPaperIds 多选状态
    store_src = (ROOT / "frontend" / "src" / "store" / "useStore.ts").read_text(encoding="utf-8")
    assert "selectedPaperIds" in store_src, "useStore 缺 selectedPaperIds 多选状态"
    assert "selectPaper(id" in store_src and "additive" in store_src, (
        "useStore.selectPaper 缺 additive 参数 (shift-click 多选)"
    )


# ===== D6: ChangelogModal =====
def test_d6_changelog_modal_has_4_entries():
    """ChangelogModal 至少 4 条 (R10.5.54/55/59 三版本 + R10.5.53)."""
    src = (ROOT / "frontend" / "src" / "components" / "ChangelogModal.tsx").read_text(encoding="utf-8")
    # 数 ENTRIES 数组里 'version:' 字段
    import re
    versions = re.findall(r"version:\s*'([^']+)'", src)
    assert len(versions) >= 4, f"D6 应有 ≥4 个升级条目, 实际 {len(versions)}"
    # 必须包含 R10.5.59 (本次主要迭代) + R10.5.55 + R10.5.54
    must_have = ["R10.5.59", "R10.5.55", "R10.5.54"]
    for kw in must_have:
        assert kw in src, f"D6 changelog 缺关键字: {kw}"


def test_d6_footer_link_in_app():
    """App.tsx 挂载 ChangelogModal + footer 有 changelog 入口."""
    src = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    # R10.5.54: openChangelog action 在 useStore 暴露
    assert "openChangelog" in src, "App.tsx 缺 openChangelog 调用"
    assert "<ChangelogModal" in src, "App.tsx 缺 ChangelogModal 挂载"
    # Footer 也要有 changelog 入口
    assert "actions.openChangelog" in src, "App.tsx footer 缺 actions.openChangelog"


# ===== D7: P2 清理 (R10.5.54 重构版) =====
def test_d7_storage_keys_lib_exists():
    """storage key 集中到 lib/storageKeys.ts (R10.5.30 D7 保留)."""
    lib_path = ROOT / "frontend" / "src" / "lib" / "storageKeys.ts"
    assert lib_path.exists()
    src = lib_path.read_text(encoding="utf-8")
    # R10.5.54+: 5 个核心 key + locale / runtimeMode / layoutMode / darkMode (legacy)
    for kw in ["theme", "apiKey", "formState", "recentSearches", "locale", "runtimeMode"]:
        assert kw in src, f"D7: storageKeys.ts 缺 {kw}"


def test_d7_no_obsolete_files():
    """R10.5.59 整文件删除后,旧文件不应再存在."""
    obsolete_files = [
        "frontend/src/hooks/useSearch.ts",
        "frontend/src/lib/useLocalStorage.ts",
        "frontend/src/lib/paperFilters.ts",
        "frontend/src/components/QueryPanel.tsx",
        "frontend/src/components/GraphPanel.tsx",
        "frontend/src/components/SettingsView.tsx",
        "frontend/src/components/CockpitDashboard.tsx",
        "frontend/src/components/CostDashboard.tsx",
        "frontend/src/components/EvolutionSlider.tsx",
        "frontend/src/components/LoginDialog.tsx",
        "frontend/src/contexts/AppContext.tsx",
        "frontend/src/contexts/SelectionContext.tsx",
        "frontend/src/contexts/UIContext.tsx",
    ]
    for f in obsolete_files:
        path = ROOT / f
        assert not path.exists(), f"D7: {f} 应已删除 (R10.5.54/59 cleanup)"


def test_d7_store_replaces_contexts():
    """useStore 取代 3 Contexts + 13 useState."""
    store_src = (ROOT / "frontend" / "src" / "store" / "useStore.ts").read_text(encoding="utf-8")
    assert "useSyncExternalStore" in store_src, "useStore 应使用 useSyncExternalStore"
    # 包含所有 actions
    for action in ["setView", "setTheme", "setRuntimeMode", "setLocale", "setApiKey", "setUser",
                   "openCommandPalette", "openAuthDialog",
                   "toggleSettingsCollapsed", "openChangelog", "openCompareDrawer",
                   "search", "cancelSearch", "selectPaper"]:
        assert action in store_src, f"useStore 缺 {action} action"
