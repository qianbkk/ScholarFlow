"""
R10.5.24 深度审计 P0 #3 修复测试 → R10.5.30 (D2) 翻转.

旧设计 (R10.5.24): backend/api/routes/search.py 是 dead router (implementation
reference), main.py 用 inline @app.post('/search') 等. 风险: 任何 PR 误加
`app.include_router(search_router)` 都会双挂载, 限流 / _in_flight 注册 / Depends
都漂移. 测试静态扫 main.py 源, 锁定不能挂载.

R10.5.30 (D2) 翻转: search_router 真正挂载, main.py 删 inline (1115 → 547 行).
行为完全等价, search.py router 跟 main.py 旧 inline 1:1 (含 @limiter /
Depends(get_current_user) 鉴权).

新测试覆盖 (翻转后):
  1. main.py 显式 include_router(search_router) (2 次, v1+裸 alias)
  2. main.py 不再有 inline @app.post('/search') 等 (双轨消除证据)
  3. search.py router 声明 + on_startup/on_shutdown shim (FastAPI 0.115+ 兼容)
  4. search.py 3 个 endpoint 都有 Depends(get_current_user) 鉴权
  5. search.py 注释明确写 "implementation reference" 跟迁移路径
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

MAIN_PY = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SEARCH_PY = (ROOT / "backend" / "api" / "routes" / "search.py").read_text(encoding="utf-8")


# ===== Test 1: main.py 显式 include_router(search_router) 两次 (v1+裸) =====
def test_main_py_mounts_search_router_explicitly():
    """R10.5.30 (D2) 翻转: main.py 必须 include_router(search_router) 两次,
    一次裸, 一次带 /api/v1 prefix, 双 alias 跟 health/auth/admin 一致."""
    matches = re.findall(
        r"include_router\(\s*search_router\b[^)]*\)", MAIN_PY
    )
    assert len(matches) >= 2, (
        f"main.py 应 include_router(search_router) 至少 2 次 (裸 + v1), "
        f"实际: {matches}. R10.5.30 (D2) 翻转后这是单挂载, 不是双轨."
    )
    # 必须有 prefix=API_V1_PREFIX 那个
    assert any("API_V1_PREFIX" in m for m in matches), (
        f"main.py 缺 include_router(search_router, prefix=API_V1_PREFIX) 调用: {matches}"
    )


# ===== Test 2: main.py 删了 inline search 端点 (双轨消除) =====
def test_main_py_no_inline_search_endpoints():
    """R10.5.30 (D2) 后: main.py 不能再有 @app.post('/search') 等 inline.
    这是双轨消除的证据. 旧版这些 inline 是双轨"在线"端点; 翻转后 search_router
    是唯一来源."""
    bad = []
    for pattern, desc in [
        (r"@app\.post\(['\"]\/search['\"]", "inline @app.post('/search')"),
        (r"@app\.get\(['\"]\/search\/stream['\"]", "inline @app.get('/search/stream')"),
        (r"@app\.post\(['\"]\/search\/cancel['\"]", "inline @app.post('/search/cancel')"),
    ]:
        if re.search(pattern, MAIN_PY):
            bad.append(desc)
    assert not bad, (
        f"main.py 仍有 inline search 端点 (R10.5.30 D2 没删干净): {bad}. "
        f"这些 inline 已迁到 routes/search.py, 应走 include_router."
    )


# ===== Test 3: search.py router 自身配置正确 =====
def test_search_py_router_has_fastapi_115_compat():
    """R10.5.30 (D2): search.py router 必须有 on_startup / on_shutdown shim
    (FastAPI 0.115+ APIRouter 不再含这些, include_router 调时会触发 AttributeError).
    跟 routes/admin.py / routes/auth.py 一致."""
    assert "router.on_startup = []" in SEARCH_PY, (
        "search.py 缺 on_startup shim (FastAPI 0.115+ 兼容性)"
    )
    assert "router.on_shutdown = []" in SEARCH_PY, (
        "search.py 缺 on_shutdown shim"
    )


# ===== Test 4: search.py 3 endpoint 都有鉴权 (D2 关键安全修复) =====
def test_search_py_all_endpoints_have_auth_depends():
    """R10.5.30 (D2): search() / cancel_search() / search_stream() 必须都有
    `user: User = Depends(get_current_user)` 参数. 旧版 main.py inline 有
    鉴权, search_router 抽出来时一不小心就会漏 (CG.txt P0 #1 修复)."""
    import ast
    tree = ast.parse(SEARCH_PY)
    endpoint_names = {"search", "cancel_search", "search_stream"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in endpoint_names:
                for arg in node.args.args + node.args.kwonlyargs:
                    if arg.arg == "user" and any(
                        isinstance(d, ast.Name) and d.id == "Depends"
                        for d in ast.walk(arg) if isinstance(d, ast.Call)
                    ):
                        found.add(node.name)
                        break
                    # Also check the default value (Depends in default position)
                    if arg.arg == "user":
                        # Look for Depends in defaults
                        for default in node.args.defaults + node.args.kw_defaults:
                            if default is None:
                                continue
                            for sub in ast.walk(default):
                                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "Depends":
                                    found.add(node.name)
                                    break
    missing = endpoint_names - found
    assert not missing, (
        f"search.py 端点缺鉴权 Depends(get_current_user): {missing}. "
        f"D2 翻转后这些端点必须鉴权, 否则 /search 暴露无鉴权, 违反 CG.txt P0 #1."
    )


# ===== Test 5: search.py 注释明确写"implementation reference" 跟 include_router 路径 =====
def test_search_py_docstring_marks_reference_role():
    """search.py 顶部 docstring 必须说明 R10.5.30 (D2) 翻转: router 真正挂载,
    main.py 删 inline. 防未来 PR 把 search.py 误当死代码删."""
    assert "implementation reference" in SEARCH_PY or "R10.5.30" in SEARCH_PY, (
        "search.py 缺 'implementation reference' / 'R10.5.30' 标记"
    )
    assert "main.py" in SEARCH_PY and "include_router" in SEARCH_PY, (
        "search.py 缺 main.py include_router 迁移路径说明"
    )
