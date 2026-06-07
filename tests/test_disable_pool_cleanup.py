"""DISABLE_HTTP_POOL 资源清理 (C-group) — merged test suite.

merged from test_disable_pool_client_leak.py, test_disabled_pool_cleanup.py
on 2026-06-07.

P0 bug fix: semantic_scholar.py / openalex.py in _DISABLE_POOL=True mode
previously created a fresh httpx.AsyncClient on every _get_client() call
without saving it, leaking the handles. The fix tracks all clients in a
module-level _temporary_clients set, and close_client() acloses all of them.

Sections:
  1) DISABLE_POOL mode creates unique clients (client_leak + disabled_pool_cleanup)
  2) close_client() releases all temporary clients
  3) pool mode doesn't pollute _temporary_clients
  4) defensive: empty set is no-op
"""
import asyncio

import pytest

from backend.api import semantic_scholar as ss_mod
from backend.api import openalex as oa_mod


# ===== Fixtures =====

@pytest.fixture
def disable_pool(monkeypatch):
    """强制 _DISABLE_POOL=True 并重置模块状态。"""
    for mod in (ss_mod, oa_mod):
        monkeypatch.setattr(mod, "_DISABLE_POOL", True)
        monkeypatch.setattr(mod, "_temporary_clients", set())
        monkeypatch.setattr(mod, "_client", None)
    return monkeypatch


# ============================================================
# 1) DISABLE_POOL 模式创建唯一 client 并跟踪到 _temporary_clients
# ============================================================

def test_ss_disable_pool_creates_unique_clients(disable_pool):
    """[from client_leak] DISABLE_POOL=True 下每次 _get_client() 应返回新实例（不共享池）。"""
    c1 = ss_mod._get_client()
    c2 = ss_mod._get_client()
    c3 = ss_mod._get_client()
    assert c1 is not c2 is not c3
    assert len(ss_mod._temporary_clients) == 3


def test_oa_disable_pool_creates_unique_clients(disable_pool):
    """[from client_leak] openalex 的 DISABLE_POOL 模式也应每次创建新 client。"""
    c1 = oa_mod._get_client()
    c2 = oa_mod._get_client()
    assert c1 is not c2
    assert len(oa_mod._temporary_clients) == 2


def test_ss_disable_pool_tracks_temporary_clients(disable_pool):
    """[from disabled_pool_cleanup] semantic_scholar: _get_client() 返回的 client 都被记录。"""
    c1 = ss_mod._get_client()
    c2 = ss_mod._get_client()
    c3 = ss_mod._get_client()

    assert c1 is not c2 and c2 is not c3 and c1 is not c3
    assert len(ss_mod._temporary_clients) == 3
    assert ss_mod._client is None  # DISABLE_POOL 模式不建池


def test_oa_disable_pool_tracks_temporary_clients(disable_pool):
    """[from disabled_pool_cleanup] openalex: 同样应跟踪临时 client。"""
    c1 = oa_mod._get_client()
    c2 = oa_mod._get_client()
    assert c1 is not c2
    assert len(oa_mod._temporary_clients) == 2


# ============================================================
# 2) close_client() 释放所有临时 client
# ============================================================

@pytest.mark.asyncio
async def test_ss_close_client_releases_all_temporary_clients(disable_pool):
    """[from client_leak] close_client() 必须关闭 _temporary_clients 里所有 client。"""
    created = [ss_mod._get_client() for _ in range(5)]
    assert len(ss_mod._temporary_clients) == 5
    assert all(not c.is_closed for c in created)

    await ss_mod.close_client()

    assert all(c.is_closed for c in created), "部分临时 client 未被关闭（资源泄漏）"
    assert len(ss_mod._temporary_clients) == 0


@pytest.mark.asyncio
async def test_oa_close_client_releases_all_temporary_clients(disable_pool):
    """[from client_leak] openalex 的 close_client() 也必须关闭所有临时 client。"""
    created = [oa_mod._get_client() for _ in range(4)]
    assert len(oa_mod._temporary_clients) == 4
    assert all(not c.is_closed for c in created)

    await oa_mod.close_client()

    assert all(c.is_closed for c in created)
    assert len(oa_mod._temporary_clients) == 0


@pytest.mark.asyncio
async def test_ss_close_client_releases_all_temporary(disable_pool):
    """[from disabled_pool_cleanup] close_client 后所有临时 client 都被关闭 + set 被清空。"""
    created = [ss_mod._get_client() for _ in range(5)]
    assert len(ss_mod._temporary_clients) == 5
    assert all(not c.is_closed for c in created)

    await ss_mod.close_client()

    assert all(c.is_closed for c in created), (
        f"close_client 后所有临时 client 应 is_closed=True, "
        f"实际: {[c.is_closed for c in created]}"
    )
    assert len(ss_mod._temporary_clients) == 0


@pytest.mark.asyncio
async def test_oa_close_client_releases_all_temporary(disable_pool):
    """[from disabled_pool_cleanup] openalex: close_client 同样应关闭所有临时 client。"""
    created = [oa_mod._get_client() for _ in range(4)]
    assert len(oa_mod._temporary_clients) == 4
    assert all(not c.is_closed for c in created)

    await oa_mod.close_client()

    assert all(c.is_closed for c in created)
    assert len(oa_mod._temporary_clients) == 0


# ============================================================
# 3) 池化模式不污染 _temporary_clients
# ============================================================

def test_ss_pool_mode_uses_singleton(monkeypatch):
    """[from client_leak] DISABLE_POOL=False 时 _get_client() 应返回同一单例。"""
    monkeypatch.setattr(ss_mod, "_DISABLE_POOL", False)
    monkeypatch.setattr(ss_mod, "_client", None)
    monkeypatch.setattr(ss_mod, "_temporary_clients", set())

    c1 = ss_mod._get_client()
    c2 = ss_mod._get_client()
    assert c1 is c2, "池化模式应返回同一 client 单例"
    assert len(ss_mod._temporary_clients) == 0


def test_ss_pool_mode_does_not_use_temporary_set(monkeypatch):
    """[from disabled_pool_cleanup] 池化模式不应往 _temporary_clients 加 client。"""
    monkeypatch.setattr(ss_mod, "_DISABLE_POOL", False)
    monkeypatch.setattr(ss_mod, "_client", None)
    monkeypatch.setattr(ss_mod, "_temporary_clients", set())

    c1 = ss_mod._get_client()
    c2 = ss_mod._get_client()
    assert c1 is c2
    assert len(ss_mod._temporary_clients) == 0


@pytest.mark.asyncio
async def test_ss_pool_mode_close_closes_singleton(monkeypatch):
    """[from client_leak] DISABLE_POOL=False 时 close_client() 应关闭池化单例。"""
    monkeypatch.setattr(ss_mod, "_DISABLE_POOL", False)
    monkeypatch.setattr(ss_mod, "_temporary_clients", set())

    c1 = ss_mod._get_client()
    assert ss_mod._client is c1
    assert not c1.is_closed

    await ss_mod.close_client()

    assert c1.is_closed
    assert ss_mod._client is None


# ============================================================
# 4) 防御性: 空 set 上 close_client 应是 no-op
# ============================================================

@pytest.mark.asyncio
async def test_close_client_with_empty_set_is_noop(monkeypatch):
    """[from disabled_pool_cleanup] _temporary_clients 空时 close_client() 不应抛错。"""
    monkeypatch.setattr(ss_mod, "_temporary_clients", set())
    monkeypatch.setattr(ss_mod, "_client", None)

    await ss_mod.close_client()
    assert ss_mod._client is None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
