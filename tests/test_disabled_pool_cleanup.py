"""DISABLE_HTTP_POOL 资源清理 (P0) 修复测试。

旧 bug：semantic_scholar.py / openalex.py 在 _DISABLE_POOL=True 时
每次 _get_client() 都新建 httpx.AsyncClient 但不保存到模块状态。
close_client() 只能关池化单例（永远是 None），临时 client 句柄
实际泄漏到 GC（被引用计数释放但没 aclose）。

修复：把临时 client 记到模块级 _temporary_clients set，close 时统一 aclose。

测试覆盖：
  1) test_disable_pool_tracks_temporary_clients: DISABLE_POOL=True 下
     _get_client() 返回的 client 都被记到 _temporary_clients
  2) test_close_client_releases_all_temporary: close_client() 后所有
     临时 client 都 is_closed
  3) test_pool_mode_does_not_use_temporary_set: 池化模式不污染 _temporary_clients
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


# ===== 1) DISABLE_POOL 模式跟踪临时 client =====

def test_ss_disable_pool_tracks_temporary_clients(disable_pool):
    """semantic_scholar: DISABLE_POOL=True 下 _get_client() 返回的 client 都被记录。"""
    c1 = ss_mod._get_client()
    c2 = ss_mod._get_client()
    c3 = ss_mod._get_client()

    # 3 个不同 client（DISABLE_POOL 模式不共享）
    assert c1 is not c2 and c2 is not c3 and c1 is not c3
    # 都记到 _temporary_clients set
    assert len(ss_mod._temporary_clients) == 3, (
        f"3 个 _get_client() 应记 3 个 client, 实际 {len(ss_mod._temporary_clients)}"
    )
    # 池化单例仍为 None（DISABLE_POOL 模式不建池）
    assert ss_mod._client is None


def test_oa_disable_pool_tracks_temporary_clients(disable_pool):
    """openalex: 同样应跟踪临时 client。"""
    c1 = oa_mod._get_client()
    c2 = oa_mod._get_client()
    assert c1 is not c2
    assert len(oa_mod._temporary_clients) == 2


# ===== 2) close_client() 关闭所有临时 client =====

@pytest.mark.asyncio
async def test_ss_close_client_releases_all_temporary(disable_pool):
    """semantic_scholar: close_client() 后所有临时 client 都被关闭（is_closed=True）。"""
    created = [ss_mod._get_client() for _ in range(5)]
    assert len(ss_mod._temporary_clients) == 5
    # 调用前全部未关闭
    assert all(not c.is_closed for c in created), "调用前 client 应是 open 状态"

    await ss_mod.close_client()

    # 全部已关闭
    assert all(c.is_closed for c in created), (
        f"close_client 后所有临时 client 应 is_closed=True, "
        f"实际: {[c.is_closed for c in created]}"
    )
    # set 已被清空
    assert len(ss_mod._temporary_clients) == 0, (
        f"close_client 应清空 _temporary_clients, 实际 {len(ss_mod._temporary_clients)}"
    )


@pytest.mark.asyncio
async def test_oa_close_client_releases_all_temporary(disable_pool):
    """openalex: close_client() 同样应关闭所有临时 client。"""
    created = [oa_mod._get_client() for _ in range(4)]
    assert len(oa_mod._temporary_clients) == 4
    assert all(not c.is_closed for c in created)

    await oa_mod.close_client()

    assert all(c.is_closed for c in created), (
        f"openalex close_client 后 {sum(1 for c in created if c.is_closed)}/{len(created)} "
        f"已关闭"
    )
    assert len(oa_mod._temporary_clients) == 0


# ===== 3) 池化模式不污染 _temporary_clients =====

def test_ss_pool_mode_does_not_use_temporary_set(monkeypatch):
    """池化模式（DISABLE_POOL=False）不应往 _temporary_clients 加 client。"""
    monkeypatch.setattr(ss_mod, "_DISABLE_POOL", False)
    monkeypatch.setattr(ss_mod, "_client", None)
    monkeypatch.setattr(ss_mod, "_temporary_clients", set())

    c1 = ss_mod._get_client()
    c2 = ss_mod._get_client()
    # 池化模式 → 同 client 单例
    assert c1 is c2
    # 临时 set 应保持空
    assert len(ss_mod._temporary_clients) == 0, (
        f"池化模式不应记 client 到 _temporary_clients, "
        f"实际 {len(ss_mod._temporary_clients)} 个"
    )


# ===== 4) 防御性：close_client 在空 set 上是 no-op =====

@pytest.mark.asyncio
async def test_close_client_with_empty_set_is_noop(monkeypatch):
    """_temporary_clients 空时 close_client() 不应抛错。"""
    monkeypatch.setattr(ss_mod, "_temporary_clients", set())
    monkeypatch.setattr(ss_mod, "_client", None)

    # 应正常返回
    await ss_mod.close_client()
    assert ss_mod._client is None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
