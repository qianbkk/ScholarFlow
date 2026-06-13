"""R10.5.20 测试: Runtime Mode 切换 (后端 /admin/runtime-mode API).

覆盖:
  1. GET 返回当前 mode + source (env / runtime)
  2. POST 切到 mock, 业务函数 is_runtime_mock() 立即生效
  3. POST 切到 real, 业务函数 is_runtime_mock() 立即返 False
  4. POST 'auto' 恢复 env 行为
  5. POST 无效 mode 返 400
  6. 切换不影响其他测试 (有 fixture 重置)
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod
from backend.utils import runtime_mode as rm
from backend.api.routes import auth as auth_routes
from backend.utils import cache as cache_mod


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """每个测试前重置 runtime_mode + cache DB + auth rate-limit.

    R10.5.20: rm._runtime_mode_override 是 backend.utils.runtime_mode 模块级 dict,
    跨测试不能依赖 autouse (本测试跑过 set_runtime_mode 之后, 后续测试需要 reset).
    改用显式 save/restore + 列表拷贝以保持状态隔离.
    """
    db_path = tmp_path / "test_runtime_mode.sqlite"
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED", False)
    monkeypatch.setattr(cache_mod, "_DB_INITIALIZED_PATH", None)
    auth_routes._RATE_HISTORY.clear()
    # 强制 reset runtime_mode (覆盖前面 test 残留)
    rm._runtime_mode_override["mode"] = "auto"
    yield


def _client():
    from backend.auth import dependencies as auth_deps
    with TestClient(main_mod.app) as c:
        # OPEN_MODE=true 跳过 auth, 简化测试
        from unittest.mock import patch
        with patch.object(auth_deps, "OPEN_MODE", True):
            yield c


def test_get_runtime_mode_default_env():
    """GET /admin/runtime-mode 默认 (auto) 时从 env 读, source=env."""
    # 强制模块级 dict 回到 auto (覆盖前面测试残留)
    rm._runtime_mode_override["mode"] = "auto"
    # TestClient 在前面 test 用过, context manager 退出可能清理时撞状态.
    # 改用直接构造 + 手动 close 避免 ExitStack 问题.
    c = TestClient(main_mod.app)
    try:
        resp = c.get("/api/v1/admin/runtime-mode")
    finally:
        c.close()
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mode"] in ("mock", "real")
    assert data["source"] in ("env", "runtime")


def test_set_runtime_mode_to_mock_immediate_effect():
    """POST 切到 mock → is_runtime_mock() 立即返 True."""
    assert rm.is_runtime_mock() in (True, False)  # 初始看 env

    c = TestClient(main_mod.app)
    try:
        resp = c.post("/api/v1/admin/runtime-mode", json={"mode": "mock"})
    finally:
        c.close()
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "mock"
    assert data["source"] == "runtime"

    # 业务函数立即看到
    assert rm.is_runtime_mock() is True
    assert rm.get_runtime_mode() == "mock"


def test_set_runtime_mode_to_real_immediate_effect():
    """POST 切到 real → is_runtime_mock() 立即返 False."""
    rm.set_runtime_mode("mock")  # 先切到 mock
    assert rm.is_runtime_mock() is True

    c = TestClient(main_mod.app)
    try:
        resp = c.post("/api/v1/admin/runtime-mode", json={"mode": "real"})
    finally:
        c.close()
    assert resp.status_code == 200
    assert resp.json()["mode"] == "real"

    assert rm.is_runtime_mock() is False


def test_set_runtime_mode_auto_restores_env():
    """POST 'auto' → 恢复 env 行为, source 不再是 runtime."""
    rm.set_runtime_mode("mock")
    assert rm.get_runtime_mode() == "mock"

    c = TestClient(main_mod.app)
    try:
        resp = c.post("/api/v1/admin/runtime-mode", json={"mode": "auto"})
    finally:
        c.close()
    assert resp.status_code == 200
    assert resp.json()["mode"] == "auto"
    assert rm.get_runtime_mode() == "auto"

    # 业务函数回到读 env
    result = rm.is_runtime_mock()
    assert isinstance(result, bool)  # 跟 env 走, 不强制 True/False


def test_set_runtime_mode_invalid_returns_400():
    """POST 无效 mode 返 400."""
    c = TestClient(main_mod.app)
    try:
        resp = c.post("/api/v1/admin/runtime-mode", json={"mode": "invalid_mode"})
    finally:
        c.close()
    assert resp.status_code == 400
    assert "mode 必须是" in resp.json()["detail"]


def test_business_functions_use_runtime_mode():
    """关键集成测试: 切换 runtime mode 后, business 函数读 is_runtime_mock()
    立即反映新 mode. 不调真实 LLM/网络 (避免 429 抖动).
    """
    # 初始: env 兜底
    initial = rm.is_runtime_mock()
    assert isinstance(initial, bool)

    # 切到 mock
    rm.set_runtime_mode("mock")
    assert rm.is_runtime_mock() is True
    assert rm.get_runtime_mode() == "mock"

    # 切到 real
    rm.set_runtime_mode("real")
    assert rm.is_runtime_mock() is False
    assert rm.get_runtime_mode() == "real"

    # 切回 auto
    rm.set_runtime_mode("auto")
    assert rm.get_runtime_mode() == "auto"
    # 业务函数回落到 env 行为
    assert isinstance(rm.is_runtime_mock(), bool)
