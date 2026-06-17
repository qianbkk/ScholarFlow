"""R10.5.30 (D4-D7) 综合防回归测试.

D4: 本地论文库真接入
  - openalex.search_papers (mock 模式) Paper.source='local_demo'
  - local_papers_db URL 含 demo=1

D5: 多选接入
  - static check: QueryPanel 接受 selectedPaperIds / onTogglePaperSelection props
  - static check: Shift+click 调 onTogglePaperSelection

D6: ChangelogModal
  - static check: 8 个 CHANGELOG_NOTES 条目
  - 包含 D1-D6 关键修复
  - Footer 链接存在

D7: P2 清理
  - lib/paperFilters.ts 存在 + PaperFilters 类型一致
  - lib/storageKeys.ts 存在 + 5 个 key
  - useSearch.ts loadRecent 不 wipe data on write fail
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


# ===== D5: 多选接入 =====
def test_d5_query_panel_accepts_selected_paper_ids_props():
    src = (ROOT / "frontend" / "src" / "components" / "QueryPanel.tsx").read_text(encoding="utf-8")
    assert "selectedPaperIds" in src, "QueryPanel 缺 selectedPaperIds props"
    assert "onTogglePaperSelection" in src, "QueryPanel 缺 onTogglePaperSelection prop"
    # Shift+click 调 onTogglePaperSelection
    assert "e.shiftKey && onTogglePaperSelection" in src, (
        "QueryPanel Shift+click 没调 onTogglePaperSelection"
    )
    # 紫色左边框标记多选
    assert "isMultiSelected" in src, "QueryPanel 缺 isMultiSelected 视觉标记"
    assert "rgb(168, 85, 247)" in src, "QueryPanel 缺紫色左边框"


# ===== D6: ChangelogModal =====
def test_d6_changelog_modal_has_8_entries():
    src = (ROOT / "frontend" / "src" / "components" / "ChangelogModal.tsx").read_text(encoding="utf-8")
    # 数 CHANGELOG_NOTES 数组里 emoji 字段
    import re
    emojis = re.findall(r"emoji:\s*'([^']+)'", src)
    # R10.5.34: 之前硬编码 8 (D1-D6), R10.5.31 F1-F6 + R10.5.32 F1-F6 累积 6 条,
    # 现共 14 条 (8 + 6). 改为 ≥ 8 软约束, 仍守住 D1-D6 关键标识.
    assert len(emojis) >= 8, f"D6 应有 ≥8 个升级条目, 实际 {len(emojis)}"
    # 必须包含 D1-D6 关键标识 (旧 D 关键修复 + R10.5.31-32 新波)
    must_have = [
        "HttpOnly Cookie",  # D3
        "本地论文库",  # D4
        "多选论文",  # D5
        "main.py 拆",  # D2
        "critic_agent",  # D1
        "/simplify 8 项",  # simplify
        "Holographic 5 组件",  # holographic
        "Admin 后门修复",  # admin
        # R10.5.31+ 新波 (F1-F6, R10.5.32 F7)
        "D3 state pollution",  # F1
        "4-Context",  # F4
        "summarize",  # F5
        "apply_migration",  # F6
        "优雅 shutdown",  # wave 7
    ]
    for kw in must_have:
        assert kw in src, f"D6 changelog 缺关键字: {kw}"


def test_d6_footer_link_in_app():
    src = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "changelog-footer-link" in src, "App.tsx 缺 changelog footer 链接"
    # R10.5.34: R10.5.31 F4 4-Context 拆分后, setChangelogOpen 改名为
    # openChangelog (useUI() 暴露的 setter). 老 D6 测试 hardcode 旧名.
    assert "openChangelog" in src, "App.tsx 缺 openChangelog (R10.5.31 F4 后改名)"
    assert "<ChangelogModal" in src, "App.tsx 缺 ChangelogModal 挂载"


# ===== D7: P2 清理 =====
def test_d7_paper_filters_lib_exists():
    """D7 P2-3: PaperFilters 类型 + DEFAULT_FILTERS 抽到 lib/paperFilters.ts."""
    lib_path = ROOT / "frontend" / "src" / "lib" / "paperFilters.ts"
    assert lib_path.exists(), f"D7: {lib_path} 不存在"
    src = lib_path.read_text(encoding="utf-8")
    assert "export interface PaperFilters" in src
    assert "export const DEFAULT_FILTERS" in src
    # R10.5.34: R10.5.31 F4 4-Context 拆分后, PaperFilters 由
    # SelectionContext 内部 import, App.tsx 不直接用. 改验证
    # SelectionContext 用 lib/paperFilters (1 source of truth).
    selection_ctx = (
        ROOT / "frontend" / "src" / "contexts" / "SelectionContext.tsx"
    ).read_text(encoding="utf-8")
    assert "from '../lib/paperFilters'" in selection_ctx, (
        "D7: SelectionContext 没从 lib/paperFilters 导入"
    )
    # App.tsx 不应再有 inline PaperFilters 重复定义
    app_src = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "yearRange: 'all' | '1' | '3' | '5'" not in app_src, (
        "D7: App.tsx 仍有 inline PaperFilters 重复定义"
    )


def test_d7_storage_keys_lib_exists():
    """D7 P2-4: storage key 集中到 lib/storageKeys.ts."""
    lib_path = ROOT / "frontend" / "src" / "lib" / "storageKeys.ts"
    assert lib_path.exists()
    src = lib_path.read_text(encoding="utf-8")
    # 5 个 key 必须有
    for kw in ["theme", "apiKey", "formState", "recentSearches", "changelogDismissed"]:
        assert kw in src, f"D7: storageKeys.ts 缺 {kw}"


def test_d7_load_recent_no_wipe_on_write_fail():
    """D7 P2-8: migration 失败时不再 removeItem 旧 data."""
    src = (ROOT / "frontend" / "src" / "hooks" / "useSearch.ts").read_text(encoding="utf-8")
    # loadRecent 体内不应该有 "if (legacy.length) { migrated... writeLocalStorage ... removeItem }" 这种无脑 wipe
    # 新版必须用 try-catch 包 localStorage.setItem 试一次, writeOk 决定删不删
    assert "writeOk" in src, "D7 P2-8: loadRecent 缺 writeOk 标志位"
    # 移除了一行 (旧版 "writeLocalStorage ... removeItem" 直接链)
    # 简单断言: 'writeLocalStorage(RECENT_KEY, migrated.slice(0, RECENT_MAX));' 不应再出现在 loadRecent 体内
    # (新代码直接 localStorage.setItem)
    load_recent_idx = src.find("function loadRecent")
    if load_recent_idx > 0:
        window = src[load_recent_idx:load_recent_idx + 1500]
        assert "writeLocalStorage(RECENT_KEY, migrated.slice" not in window, (
            "D7 P2-8: loadRecent 仍用 writeLocalStorage (无 try-catch)"
        )
        assert "localStorage.setItem(RECENT_KEY" in window, (
            "D7 P2-8: loadRecent 改用 localStorage.setItem 试一次 (try-catch)"
        )
