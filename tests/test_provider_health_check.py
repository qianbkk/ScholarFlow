"""E2-1 测试: /providers 真实可用性检查 (不只 env 非空)

用户报告 Kimi/GLM key 在 .env 配置但实际 401 失效。原实现只检查
env 非空,导致前端选择 kimi 后 API 调用失败 → 静默 fallback mock。
修复: 在 lifespan + 定期用最小 API 调用 (max_tokens=1) 真实验证 key。
"""
import asyncio
import os
import sys
import time as _time

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, '.')

import pytest
from backend import main as main_mod
from backend.config import KIMI_API_KEY, GLM_API_KEY, MiniMax_API_KEY, DEEPSEEK_API_KEY


def test_provider_health_cache_initially_empty():
    """启动时 cache 应为空 (lifespan 异步填充)。"""
    main_mod._PROVIDER_HEALTH_CACHE.clear()
    assert main_mod._PROVIDER_HEALTH_CACHE == {}


def test_get_providers_with_keys_includes_verified_field():
    """_get_providers_with_keys 应返回 verified 字段 (True/False/None)。"""
    providers = main_mod._get_providers_with_keys()
    assert len(providers) >= 4
    for p in providers:
        assert "id" in p
        assert "name" in p
        assert "has_key" in p
        assert "verified" in p
        assert p["verified"] in (True, False, None)


@pytest.mark.asyncio
async def test_verify_minimax_real_key_succeeds():
    """MiniMax key 是用户唯一真实可用的 key, 验证应通过。"""
    if not MiniMax_API_KEY:
        pytest.skip("MiniMax key 未配置")
    ok = await main_mod._verify_provider_key("minimax")
    assert ok is True, (
        f"MiniMax key 应可用, 但 verify 返回 False. "
        f"检查 MiniMax_API_KEY 是否过期。"
    )


@pytest.mark.asyncio
async def test_verify_kimi_key_may_fail_if_expired():
    """Kimi key 在 .env 中存在但 401 失效(已知)→ 验证应 False。"""
    if not KIMI_API_KEY:
        pytest.skip("KIMI key 未配置")
    # 不强制断言 False (可能用户已更新), 但如果有 key 至少应返回 bool
    ok = await main_mod._verify_provider_key("kimi")
    assert isinstance(ok, bool)


@pytest.mark.asyncio
async def test_verify_deepseek_returns_bool():
    """DeepSeek key (无 → 应 False; 有 → bool)."""
    ok = await main_mod._verify_provider_key("deepseek")
    assert isinstance(ok, bool)
    if not DEEPSEEK_API_KEY:
        assert ok is False


@pytest.mark.asyncio
async def test_verify_unknown_provider_returns_false():
    """未知 provider id 应返回 False (不抛异常)。"""
    ok = await main_mod._verify_provider_key("nonexistent_provider")
    assert ok is False


@pytest.mark.asyncio
async def test_refresh_provider_health_cache_populates_all():
    """_refresh_provider_health_cache 应填充所有 _PROVIDER_META。"""
    main_mod._PROVIDER_HEALTH_CACHE.clear()
    await main_mod._refresh_provider_health_cache()
    # 所有 provider 都有缓存条目 (True 或 False)
    for pid in main_mod._PROVIDER_META.keys():
        assert pid in main_mod._PROVIDER_HEALTH_CACHE, (
            f"provider {pid} 应有缓存条目"
        )
        cached_value, cached_ts = main_mod._PROVIDER_HEALTH_CACHE[pid]
        assert isinstance(cached_value, bool)
        assert (_time.time() - cached_ts) < 60  # 刚写入


def test_get_providers_uses_cache_when_fresh():
    """cache 在 TTL 内时, _get_providers_with_keys 应读 cache (不再 env 估计)。"""
    # 手动塞一个 "verified=True" 的 cache
    main_mod._PROVIDER_HEALTH_CACHE["minimax"] = (True, _time.time())
    providers = main_mod._get_providers_with_keys()
    p = next(p for p in providers if p["id"] == "minimax")
    assert p["verified"] is True
    assert p["has_key"] is True


def test_get_providers_uses_cache_when_negative():
    """cache 验证失败时, has_key 应为 False (即使 env 非空)。"""
    # 假设 Kimi key 在 env 但实际失效
    main_mod._PROVIDER_HEALTH_CACHE["kimi"] = (False, _time.time())
    providers = main_mod._get_providers_with_keys()
    p = next(p for p in providers if p["id"] == "kimi")
    assert p["verified"] is False
    if KIMI_API_KEY:
        # env 有但验证失败 → has_key 必须 False
        assert p["has_key"] is False, (
            "Kimi key 在 .env 但 401 失效时, has_key 必须 False (不只 env 非空)"
        )


if __name__ == "__main__":
    # 调试入口
    test_provider_health_cache_initially_empty()
    test_get_providers_with_keys_includes_verified_field()
    print("=== sync tests pass ===")
    asyncio.run(test_verify_minimax_real_key_succeeds())
    print("=== MiniMax verify pass ===")
    asyncio.run(test_refresh_provider_health_cache_populates_all())
    print("=== refresh pass ===")
    print("=== E2-1 provider health check tests all pass ===")
