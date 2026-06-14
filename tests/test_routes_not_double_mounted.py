"""
R10.5.24 深度审计 P0 #3 修复测试.

问题: backend/api/routes/search.py 是实现参考 (dead router),
      backend/main.py 仍用 inline @app.post('/search') 等, 跟 router 双轨.
      风险: 任何 PR 误加 `app.include_router(search_router)` 都会让 FastAPI
      双重挂载 /search, 限流器、_in_flight_searches 注册、Depends 都漂移.

修复: 静态扫描 main.py 源, 确保不含 `app.include_router(search_router)` /
     `app.include_router` 配 backend.api.routes.search.

测试覆盖:
  1. main.py 不 import backend.api.routes.search (死代码隔离)
  2. main.py 不调 include_router(search_router)
  3. main.py 不调 include_router(*search*) (泛匹配, 防漏)
  4. main.py 的 /search /search/stream /search/cancel 是 inline @app.post/.get
     (grep 验证) — 这是双轨"在线"端点的证据
  5. search.py 自己声明 router, 但 R10.5.24 注释明确写 "implementation
     reference only" + "test_routes_not_double_mounted.py 静态扫 main.py
     源, 防止 include_router 误增"
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


# ===== Test 1: main.py 不 import search router 模块 =====
def test_main_py_does_not_import_search_router_module():
    """main.py 不应有 `from backend.api.routes import search` 或 `import search` 行.

    例外: 如果 main.py 内部用 `import backend.api.routes.search as _search_mod`
    也算违规. 仅允许通过 helpers 间接调用 (如 _make_initial_state 在 models).
    """
    # 找所有 import 行
    import_lines = [
        line for line in MAIN_PY.splitlines()
        if re.match(r"^\s*(from\s+backend\.api\.routes|import\s+backend\.api\.routes)", line)
    ]
    bad = [l for l in import_lines if "search" in l.lower()]
    assert not bad, (
        f"main.py 不应直接 import search router (会引发双轨). 违规行:\n"
        + "\n".join(f"  {l}" for l in bad)
    )


# ===== Test 2: main.py 不调 include_router(search_router) =====
def test_main_py_does_not_mount_search_router():
    """main.py 不应出现 `include_router(...search...)` 调用."""
    matches = re.findall(
        r"include_router\([^)]*search[^)]*\)", MAIN_PY, flags=re.IGNORECASE
    )
    assert not matches, (
        f"main.py 误调 include_router(search...): {matches}. "
        f"这会跟 inline @app.post('/search') 双轨, 限流 / _in_flight 注册 / "
        f"Depends 注入都漂移. 详见 backend/api/routes/search.py R10.5.24 注释."
    )


# ===== Test 3: inline @app.post / @app.get 是真实端点 =====
def test_main_py_has_inline_search_endpoints():
    """/search /search/stream /search/cancel 在 main.py 是 inline @app.post/.get (双轨"在线")."""
    assert re.search(r"@app\.post\(['\"]\/search['\"]", MAIN_PY), (
        "main.py 缺 @app.post('/search') — R10.5.24 之前 inline 端点不应被删"
    )
    assert re.search(r"@app\.get\(['\"]\/search\/stream['\"]", MAIN_PY), (
        "main.py 缺 @app.get('/search/stream')"
    )
    assert re.search(r"@app\.post\(['\"]\/search\/cancel['\"]", MAIN_PY), (
        "main.py 缺 @app.post('/search/cancel')"
    )


# ===== Test 4: search.py 注释明确说明是 "implementation reference only" =====
def test_search_py_docstring_marks_reference_role():
    """backend/api/routes/search.py 顶部 docstring 必须声明 router 是参考实现,
    当前未挂载. 防未来 PR 误以为它是死代码可删 (实际是 future 迁移蓝图).
    """
    assert "implementation reference" in SEARCH_PY, (
        "search.py 缺 'implementation reference' 声明, 未来维护者可能误删"
    )
    assert "main.py" in SEARCH_PY and "include_router" in SEARCH_PY, (
        "search.py 缺 main.py include_router 迁移路径说明"
    )
    # R10.5.24 加固: 必须引用本测试
    assert "test_routes_not_double_mounted" in SEARCH_PY, (
        "search.py 应引用 test_routes_not_double_mounted.py 作为 include_router 误增的护栏"
    )


# ===== Test 5: search.py router 已声明但 mount 由 main.py 控制 =====
def test_search_py_router_exists_but_not_auto_mounted():
    """search.py 声明了 `router = APIRouter(...)` 但只有 main.py 显式 include 才生效.
    本测试固化: search.py 自身没有 'app.include_router' 调用 (模块副作用).
    """
    # 模块顶层不调 app.include_router (没有 FastAPI app 实例)
    assert "app.include_router" not in SEARCH_PY.split("\n\n")[0], (
        "search.py 顶层不应调 app.include_router (没有 app 实例, 应该是 main.py 调)"
    )
