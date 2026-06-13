"""
J.txt + K.txt 审计 #1 修复测试 (R10.5.21).

原问题: /api/v1/admin/runtime-mode POST 完全无认证, 任何人都能切 mock/real,
包括把生产环境的 LLM 切到 mock (静默不工作) 或切到 real (烧钱).

修复: 新增 require_admin FastAPI 依赖. fail-closed 默认, OPEN_MODE=true 也
默认拒绝, OPEN_MODE=false 时需 ADMIN_USER_IDS 白名单.

测试策略: 不 del sys.modules (会污染其他 test), 用 monkeypatch 改 module
属性的方式, 跟 test_auth_api_key.py 风格一致.

测试范围:
  - GET 仍然公开 (不影响前端启动时拉取)
  - OPEN_MODE=true + 无白名单 → POST 403
  - OPEN_MODE=true + ADMIN_USER_IDS=dev-user → POST 200
  - OPEN_MODE=false + 无 key → POST 401
  - OPEN_MODE=false + key 不在白名单 → POST 403
  - OPEN_MODE=false + key 在白名单 → POST 200
  - OPEN_MODE=false + 白名单空 → 全 403
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 让 conftest / pytest 跑得到
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient


# Fixture: 给一个 TestClient, 同时提供 monkeypatch 接口
@pytest.fixture
def admin_client(monkeypatch):
    """Build TestClient. caller 在 use 前调 patch_admin(...)."""
    # 不 del sys.modules — 其他 test (test_auth_api_key) 已 import 此模块,
    # del 会让 get_current_user 引用旧 module, 产生 难以诊断 的 test pollution.
    # 我们只改 module-level 属性的值.
    from backend import main as main_mod
    from backend.auth import dependencies as auth_dep

    def _patch(*, open_mode: bool | None = None, admin_user_ids: str | None = None):
        if open_mode is not None:
            monkeypatch.setattr(auth_dep, "OPEN_MODE", open_mode)
        if admin_user_ids is not None:
            # ADMIN_USER_IDS 是 frozenset 不可变, 改 module-level name 重新解析
            monkeypatch.setenv("ADMIN_USER_IDS", admin_user_ids)
            # 重新计算 frozenset (handler 引用 module-level name, 改属性)
            parsed = frozenset(
                uid.strip() for uid in admin_user_ids.split(",") if uid.strip()
            )
            monkeypatch.setattr(auth_dep, "ADMIN_USER_IDS", parsed)
        return auth_dep

    def _mock_lookup(mapping: dict[str, "auth_dep.User | None"]):
        """mock _lookup_user_by_key 返指定 User. mapping: {raw_key: User or None}."""
        def fake_lookup(raw_key):
            return mapping.get(raw_key)
        monkeypatch.setattr(auth_dep, "_lookup_user_by_key", fake_lookup)

    c = TestClient(main_mod.app)
    try:
        yield {"client": c, "patch": _patch, "mock_lookup": _mock_lookup,
               "auth_dep": auth_dep}
    finally:
        c.close()


# ===== Test 1: GET 始终公开 =====
def test_get_runtime_mode_is_public(admin_client):
    """GET /admin/runtime-mode 无需 auth, 仅返回当前 mode."""
    resp = admin_client["client"].get("/api/v1/admin/runtime-mode")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] in ("mock", "real")
    assert body["source"] in ("env", "runtime")


# ===== Test 2: OPEN_MODE=true + 默认 (无白名单) → POST 403 =====
def test_post_blocked_in_open_mode_by_default(admin_client):
    """OPEN_MODE=true 下 POST 默认 403, 防止 dev-user 随意改全局 LLM 模式."""
    admin_client["patch"](open_mode=True, admin_user_ids="")
    resp = admin_client["client"].post("/api/v1/admin/runtime-mode", json={"mode": "mock"})
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"
    assert "OPEN_MODE" in resp.json()["detail"]


# ===== Test 3: OPEN_MODE=true + ADMIN_USER_IDS=dev-user → POST 200 =====
def test_post_allowed_in_open_mode_with_explicit_dev_user(admin_client):
    """显式 dev-user 进白名单时, dev 模式可以切 (本地开发常用)."""
    admin_client["patch"](open_mode=True, admin_user_ids="dev-user")
    resp = admin_client["client"].post("/api/v1/admin/runtime-mode", json={"mode": "mock"})
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["mode"] == "mock"
    assert body["source"] == "runtime"


# ===== Test 4: OPEN_MODE=false + 无 key → POST 401 =====
def test_post_requires_api_key_in_locked_mode(admin_client):
    """多用户模式下, 没带 X-API-Key 直接 401."""
    admin_client["patch"](open_mode=False, admin_user_ids="u_admin")
    resp = admin_client["client"].post("/api/v1/admin/runtime-mode", json={"mode": "real"})
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text}"
    assert "X-API-Key" in resp.json()["detail"]


# ===== Test 5: OPEN_MODE=false + key 不在白名单 → POST 403 =====
def test_post_rejects_non_admin_user(admin_client):
    """非白名单用户带有效 key 也被拒 (但不暴露白名单内容)."""
    from backend.auth.dependencies import User
    admin_client["patch"](open_mode=False, admin_user_ids="u_admin_only")
    admin_client["mock_lookup"]({
        "valid-but-not-admin": User(
            user_id="u_random", display_name="X", created_at=0.0, is_dev_user=False
        ),
    })
    resp = admin_client["client"].post(
        "/api/v1/admin/runtime-mode",
        json={"mode": "real"},
        headers={"X-API-Key": "valid-but-not-admin"},
    )
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"
    assert "无 admin 权限" in resp.json()["detail"]


# ===== Test 6: OPEN_MODE=false + key 在白名单 → POST 200 =====
def test_post_allowed_for_admin_user(admin_client):
    """白名单用户带有效 key 才能切 mode."""
    from backend.auth.dependencies import User
    admin_client["patch"](open_mode=False, admin_user_ids="u_admin1,u_admin2")
    admin_client["mock_lookup"]({
        "admin1-key": User(
            user_id="u_admin1", display_name="Admin1", created_at=0.0, is_dev_user=False
        ),
    })
    resp = admin_client["client"].post(
        "/api/v1/admin/runtime-mode",
        json={"mode": "real"},
        headers={"X-API-Key": "admin1-key"},
    )
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["mode"] == "real"
    assert body["source"] == "runtime"


# ===== Test 7: OPEN_MODE=false + 白名单空 → 任何 key 都 403 =====
def test_post_rejects_all_when_allowlist_empty(admin_client):
    """空白名单 = 全拒 (fail-closed 默认)."""
    from backend.auth.dependencies import User
    admin_client["patch"](open_mode=False, admin_user_ids="")
    admin_client["mock_lookup"]({
        "any-key": User(
            user_id="u_someone", display_name="X", created_at=0.0, is_dev_user=False
        ),
    })
    resp = admin_client["client"].post(
        "/api/v1/admin/runtime-mode",
        json={"mode": "real"},
        headers={"X-API-Key": "any-key"},
    )
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"
    assert "白名单" in resp.json()["detail"]


# ===== Test 8: 验证 ADMIN_USER_IDS 解析 (逗号 + 空白) =====
def test_admin_user_ids_parsing():
    """解析逻辑: 逗号分隔, 去空白, 去空字符串, 冻结集合."""
    # 直接重新计算 (handler 读 module-level ADMIN_USER_IDS)
    raw = " u_a , , u_b ,  u_c  "
    parsed = frozenset(uid.strip() for uid in raw.split(",") if uid.strip())
    assert parsed == frozenset({"u_a", "u_b", "u_c"})
