"""DISABLE_HTTP_POOL 资源泄漏修复测试。

P0 bug：semantic_scholar.py / openalex.py 在 _DISABLE_POOL=True 时
每次 _get_client() 都新建 httpx.AsyncClient 但不保存到模块状态，
close_client() 只能关池化单例（永远是 None），临时 client 句柄泄漏。

修复：把临时 client 记到模块级 _temporary_clients set，close 时统一 aclose。

测试要点：
  1) DISABLE_POOL 模式下多次 _get_client() 返回的 client 不重复
  2) close_client() 之后所有临时 client 都被关闭
  3) close_client() 后 _temporary_clients 被清空
  4) 修复对 semantic_scholar 和 openalex 都生效
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
        # 清空临时 client 集合 + 单例
        monkeypatch.setattr(mod, "_temporary_clients", set())
        monkeypatch.setattr(mod, "_client", None)
    return monkeypatch


def _closed_clients(temp_set):
    """统计临时 set 中已关闭的 client 数。"""
    return sum(1 for c in temp_set if c.is_closed)


# ===== semantic_scholar 测试 =====

def test_ss_disable_pool_creates_unique_clients(disable_pool):
    """DISABLE_POOL=True 下每次 _get_client() 应返回新实例（不共享池）。"""
    c1 = ss_mod._get_client()
    c2 = ss_mod._get_client()
    c3 = ss_mod._get_client()
    assert c1 is not c2 is not c3, "DISABLE_POOL 模式应每次创建新 client"
    # 都被记录到临时 set
    assert len(ss_mod._temporary_clients) == 3


@pytest.mark.asyncio
async def test_ss_close_client_releases_all_temporary_clients(disable_pool):
    """close_client() 必须关闭 _temporary_clients 里所有 client。"""
    # 创建 5 个临时 client（先记下引用，因为 close_client 会清空 set）
    created = [ss_mod._get_client() for _ in range(5)]
    assert len(ss_mod._temporary_clients) == 5
    # 调用前全部未关闭
    assert all(not c.is_closed for c in created)

    await ss_mod.close_client()

    # 全部已关闭（用先前保存的引用验证）
    assert all(c.is_closed for c in created), "部分临时 client 未被关闭（资源泄漏）"
    # set 已被清空
    assert len(ss_mod._temporary_clients) == 0


# ===== openalex 测试 =====

def test_oa_disable_pool_creates_unique_clients(disable_pool):
    """openalex 的 DISABLE_POOL 模式也应每次创建新 client。"""
    c1 = oa_mod._get_client()
    c2 = oa_mod._get_client()
    assert c1 is not c2
    assert len(oa_mod._temporary_clients) == 2


@pytest.mark.asyncio
async def test_oa_close_client_releases_all_temporary_clients(disable_pool):
    """openalex 的 close_client() 也必须关闭所有临时 client。"""
    created = [oa_mod._get_client() for _ in range(4)]
    assert len(oa_mod._temporary_clients) == 4
    assert all(not c.is_closed for c in created)

    await oa_mod.close_client()

    assert all(c.is_closed for c in created), "部分临时 client 未被关闭（资源泄漏）"
    assert len(oa_mod._temporary_clients) == 0


# ===== 回归：非 DISABLE_POOL 模式仍正常 =====

def test_ss_pool_mode_uses_singleton(monkeypatch):
    """DISABLE_POOL=False 时 _get_client() 应返回同一单例。"""
    monkeypatch.setattr(ss_mod, "_DISABLE_POOL", False)
    monkeypatch.setattr(ss_mod, "_client", None)
    monkeypatch.setattr(ss_mod, "_temporary_clients", set())

    c1 = ss_mod._get_client()
    c2 = ss_mod._get_client()
    assert c1 is c2, "池化模式应返回同一 client 单例"
    # 临时 set 应保持空
    assert len(ss_mod._temporary_clients) == 0


@pytest.mark.asyncio
async def test_ss_pool_mode_close_closes_singleton(monkeypatch):
    """DISABLE_POOL=False 时 close_client() 应关闭池化单例。"""
    monkeypatch.setattr(ss_mod, "_DISABLE_POOL", False)
    monkeypatch.setattr(ss_mod, "_temporary_clients", set())

    c1 = ss_mod._get_client()
    assert ss_mod._client is c1
    assert not c1.is_closed

    await ss_mod.close_client()

    assert c1.is_closed
    assert ss_mod._client is None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
