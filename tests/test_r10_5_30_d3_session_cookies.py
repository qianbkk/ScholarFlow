"""R10.5.30 (D3 P0-1) HttpOnly cookie 鉴权修复.

对应 CG.txt §1 P1 #4 真修: session 用 HttpOnly cookie, 长期 api_key 仍返
(向后兼容 R10.5.28), 但前端可选改用 credentials: 'include' + X-CSRF-Token.

覆盖:
  1. session_store: 创建 / 解析 / 过期 / 删除 / GC
  2. /auth/login: 返 Set-Cookie (HttpOnly + SameSite=Strict) + api_key
  3. /auth/register: 同样 Set-Cookie
  4. /auth/logout: 删 session + 清 cookie
  5. /auth/csrf-token: 返 session 里的 csrf_token
  6. require_csrf 依赖: 缺/错/匹配 三分支
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# R10.5.30 (D3): 这套测试全跑在 OPEN_MODE=false 下 (测试 cookie 鉴权真实路径).
# 必须在 import backend 之前设, 让 backend.auth.dependencies 模块级 OPEN_MODE 生效.
os.environ["OPEN_MODE"] = "false"


# R10.5.30 (D3): 强制 lifespan 替代品 — 直接调 _init_db_once() 让 users / budget_user
# / sessions 表全部就绪, TestClient context manager 在 OPEN_MODE 切换时不可靠.
# 关键: 必须 monkeypatch _DB 指向 auth.sqlite, 因为 _init_db 用默认 _DB (=cache.sqlite)
# 而 auth 表跟 users 表只在 role='auth' 路径建. 测试需要 2 步:
#   1) 把 _DB 临时指向 auth.sqlite 路径, init (建 users 表到 auth.sqlite)
#   2) 恢复 _DB, 让其他 role (cache/budget) 也 init
def _ensure_db():
    import backend.utils.cache as _cache
    from pathlib import Path
    auth_db = _cache._DB_PATHS["auth"]
    orig_db = _cache._DB
    # 步骤 1: 建 users 表到 auth.sqlite
    _cache._DB = auth_db
    _cache._DB_INITIALIZED = False
    _cache._DB_INITIALIZED_PATH = None
    _cache._init_db_once()
    # 步骤 2: 恢复默认 _DB, 让 cache / budget role 也 init
    _cache._DB = orig_db
    _cache._DB_INITIALIZED = False
    _cache._DB_INITIALIZED_PATH = None
    _cache._init_db_once()
    # R10.5.30 (D3): sessions 表由 session_store 懒建, 但首次访问也会建.
    from backend.utils.session_store import _ensure_sessions_table
    _ensure_sessions_table()


# ===== 1. session_store 行为 =====
def test_session_store_create_and_resolve():
    """session_store.create_session + resolve_session 配对."""
    from backend.utils.session_store import create_session, resolve_session
    sess = create_session("u_test_d3_1", ip_address="127.0.0.1")
    assert sess["session_id"].startswith("ss_")
    assert len(sess["csrf_token"]) > 30
    assert sess["ttl_sec"] == 86400
    resolved = resolve_session(sess["session_id"])
    assert resolved is not None
    assert resolved["user_id"] == "u_test_d3_1"
    assert resolved["csrf_token"] == sess["csrf_token"]


def test_session_store_resolve_unknown_returns_none():
    from backend.utils.session_store import resolve_session
    assert resolve_session("ss_nonexistent_xyz") is None
    assert resolve_session("") is None


def test_session_store_resolve_expired_returns_none():
    """过期 session 返 None. 用 touch_session 跟 DELETE 模拟过期."""
    from backend.utils.session_store import create_session, resolve_session
    from backend.utils.cache import _connect_with_wal
    sess = create_session("u_test_d3_expired")
    # 直接 UPDATE expires_at 到过去
    _c = _connect_with_wal("auth")
    try:
        _c.execute(
            "UPDATE sessions SET expires_at=0.0 WHERE session_id=?",
            (sess["session_id"],),
        )
        _c.commit()
    finally:
        _c.close()
    assert resolve_session(sess["session_id"]) is None


def test_session_store_delete():
    from backend.utils.session_store import create_session, delete_session, resolve_session
    sess = create_session("u_test_d3_del")
    assert resolve_session(sess["session_id"]) is not None
    delete_session(sess["session_id"])
    assert resolve_session(sess["session_id"]) is None


def test_session_store_gc_removes_expired():
    from backend.utils.session_store import create_session, gc_sessions
    from backend.utils.cache import _connect_with_wal
    # 加 3 个过期
    _c = _connect_with_wal("auth")
    try:
        for i in range(3):
            _c.execute(
                "INSERT INTO sessions (session_id, user_id, csrf_token, expires_at, created_at, last_seen_at) "
                "VALUES (?, ?, ?, 0.0, 0.0, 0.0)",
                (f"ss_expired_{i}_{int(time.time()*1000)}", "u_x", "csrf_x"),
            )
        _c.commit()
    finally:
        _c.close()
    deleted = gc_sessions()
    assert deleted >= 3, f"GC 应清 ≥3 行, 实际 {deleted}"


# ===== 2-3. /auth/login + /auth/register Set-Cookie =====
def test_login_sets_session_and_csrf_cookies(monkeypatch):
    """/auth/login Set-Cookie: sf_session_id (HttpOnly) + sf_csrf_token (JS-readable).

    R10.5.34: 跟 test_register 一致 - reload + 重新 import main, 拿到
    新的 app 引用 (含新 register/login endpoint).
    """
    import importlib
    import backend.auth.dependencies
    import backend.api.routes.auth
    importlib.reload(backend.auth.dependencies)
    importlib.reload(backend.api.routes.auth)
    import backend.auth.dependencies as _deps
    import backend.api.routes.auth as _auth_mod
    orig_deps_om = _deps.OPEN_MODE
    orig_auth_om = _auth_mod.OPEN_MODE
    _deps.OPEN_MODE = False
    _auth_mod.OPEN_MODE = False
    try:
        _ensure_db()
        from fastapi.testclient import TestClient
        import sys
        if "backend.main" in sys.modules:
            importlib.reload(sys.modules["backend.main"])
        import backend.main as m
        with TestClient(m.app) as c:
            email = f"d3_login_{int(time.time()*1000)}@x.com"
            c.post("/auth/register", json={"email": email, "password": "long_enough_pwd"})
            r = c.post("/auth/login", json={"email": email, "password": "long_enough_pwd"})
        assert r.status_code == 200, r.text
        set_cookie = r.headers.get("set-cookie", "")
        assert "sf_session_id=" in set_cookie, f"login 缺 sf_session_id cookie: {set_cookie[:200]}"
        assert "sf_csrf_token=" in set_cookie, f"login 缺 sf_csrf_token cookie: {set_cookie[:200]}"
        assert "HttpOnly" in set_cookie, "sf_session_id 必须 HttpOnly"
        assert "SameSite=Strict" in set_cookie or "samesite=strict" in set_cookie.lower()
        data = r.json()
        assert "api_key" in data
        assert data["api_key"].startswith("sf_")
    finally:
        _deps.OPEN_MODE = orig_deps_om
        _auth_mod.OPEN_MODE = orig_auth_om


def test_register_sets_session_and_csrf_cookies():
    """/auth/register 同样 Set-Cookie.

    R10.5.34 关键修复: FastAPI app 在 startup 时 import routes/auth,
    register 函数作为 endpoint 绑定到 app.router. reload routes/auth 不会
    替换 app 已绑定的 function 对象. 解法: reload 后, **重新构造 FastAPI app**
    (重新 include_router 拿新 register). TestClient 用新 app 跑.
    """
    import importlib
    import backend.auth.dependencies
    import backend.api.routes.auth
    importlib.reload(backend.auth.dependencies)
    importlib.reload(backend.api.routes.auth)
    import backend.auth.dependencies as _deps
    import backend.api.routes.auth as _auth_mod
    orig_deps_om = _deps.OPEN_MODE
    orig_auth_om = _auth_mod.OPEN_MODE
    _deps.OPEN_MODE = False
    _auth_mod.OPEN_MODE = False
    try:
        _ensure_db()
        from fastapi.testclient import TestClient
        # reload 后, 重新 import main 让 app 重新 include_router (拿新 register)
        import sys
        if "backend.main" in sys.modules:
            importlib.reload(sys.modules["backend.main"])
        import backend.main as m
        with TestClient(m.app) as c:
            r = c.post("/auth/register", json={
            "email": f"d3_reg_{int(time.time()*1000)}@x.com",
            "display_name": "D3",
            "password": "long_enough_pwd",
        })
        assert r.status_code == 200, r.text
        set_cookie = r.headers.get("set-cookie", "")
        assert "sf_session_id=" in set_cookie
        assert "sf_csrf_token=" in set_cookie
    finally:
        _deps.OPEN_MODE = orig_deps_om
        _auth_mod.OPEN_MODE = orig_auth_om


# ===== 4. /auth/logout =====
def test_logout_clears_session_and_cookies(monkeypatch):
    """R10.5.34: 已有 importlib.reload, 保留."""
    monkeypatch.setenv("OPEN_MODE", "false")
    import importlib
    import backend.auth.dependencies
    importlib.reload(backend.auth.dependencies)
    import backend.api.routes.auth
    importlib.reload(backend.api.routes.auth)
    _ensure_db()
    from fastapi.testclient import TestClient
    import backend.main as m
    c = TestClient(m.app)
    email = f"d3_logout_{int(time.time()*1000)}@x.com"
    c.post("/auth/register", json={"email": email, "password": "long_enough_pwd"})
    login_r = c.post("/auth/login", json={"email": email, "password": "long_enough_pwd"})
    assert login_r.status_code == 200
    logout_r = c.post("/auth/logout")
    assert logout_r.status_code == 200
    assert logout_r.json()["logged_out"] is True
    set_cookie = logout_r.headers.get("set-cookie", "")
    assert "sf_session_id=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()
    monkeypatch.setenv("OPEN_MODE", "true")
    importlib.reload(backend.auth.dependencies)
    importlib.reload(backend.api.routes.auth)


# ===== 5. /auth/csrf-token =====
def test_csrf_token_endpoint_returns_session_csrf(monkeypatch):
    monkeypatch.setenv("OPEN_MODE", "false")
    import importlib
    import backend.auth.dependencies
    importlib.reload(backend.auth.dependencies)
    import backend.api.routes.auth
    importlib.reload(backend.api.routes.auth)
    _ensure_db()
    from fastapi.testclient import TestClient
    import backend.main as m
    with TestClient(m.app) as c:
        email = f"d3_csrf_{int(time.time()*1000)}@x.com"
        c.post("/auth/register", json={"email": email, "password": "long_enough_pwd"})
        c.post("/auth/login", json={"email": email, "password": "long_enough_pwd"})
        r = c.get("/auth/csrf-token")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "csrf_token" in data
    assert len(data["csrf_token"]) > 30
    assert data["expires_in"] > 0
    monkeypatch.setenv("OPEN_MODE", "true")
    importlib.reload(backend.auth.dependencies)
    importlib.reload(backend.api.routes.auth)


def test_csrf_token_no_session_returns_401():
    """无 session + OPEN_MODE=false → 401. dev-user (OPEN_MODE=true) 不走
    这条, 改成单独验 dev-user 可访问."""
    import backend.auth.dependencies as _deps
    import backend.api.routes.auth as _auth_mod
    orig_deps_om = _deps.OPEN_MODE
    orig_auth_om = _auth_mod.OPEN_MODE
    _deps.OPEN_MODE = False
    _auth_mod.OPEN_MODE = False
    try:
        from fastapi.testclient import TestClient
        import backend.main as m
        with TestClient(m.app) as c:
            r = c.get("/auth/csrf-token")
        assert r.status_code == 401, r.text
    finally:
        # 恢复 OPEN_MODE 状态, 让后续 dev-user 路径测试还能走
        _deps.OPEN_MODE = True
        _auth_mod.OPEN_MODE = True
    # OPEN_MODE=true → dev-user 可访问 (验证 OPEN_MODE 旁路)
    from fastapi.testclient import TestClient
    import backend.main as m
    with TestClient(m.app) as c:
        r2 = c.get("/auth/csrf-token")
    assert r2.status_code == 200, r2.text


# ===== 6. require_csrf 校验 =====
def test_require_csrf_missing_header_returns_403():
    """OPEN_MODE=false + 缺 X-CSRF-Token → 403."""
    import backend.api.routes.auth as _auth_mod
    orig = _auth_mod.OPEN_MODE
    _auth_mod.OPEN_MODE = False
    try:
        from backend.api.routes.auth import require_csrf
        from starlette.requests import Request
        # mock request 没 cookie
        scope = {"type": "http", "headers": []}
        req = Request(scope)
        import asyncio
        try:
            asyncio.run(require_csrf(req, x_csrf_token=None))
            assert False, "should have raised HTTPException"
        except Exception as e:
            from fastapi import HTTPException
            assert isinstance(e, HTTPException)
            assert e.status_code == 403
    finally:
        _auth_mod.OPEN_MODE = orig
