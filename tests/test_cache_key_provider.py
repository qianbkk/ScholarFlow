"""cache_key 含 provider 维度 (P1) 修复测试。

旧 bug：cache_key 只 hash (query, max_iterations, budget)，
导致用 kimi 搜的缓存结果被 glm/anthropic 等其他 provider 误命中。
→ 跨 LLM provider 同 query 缓存污染。

修复：cache_key 增加 provider 参数（默认 None → "default"）。
不同 provider 生成不同 key，避免串。

测试覆盖：
  1) test_cache_key_differs_by_provider: kimi vs minimax key 必须不同
  2) test_cache_key_default_provider_backward_compat: 无 provider → "default"
  3) test_cache_key_same_provider_same_key: 同 provider 同 query → 相同 key
  4) test_cache_key_signature_accepts_provider: 签名包含 provider 参数
"""
import inspect

import pytest

from backend.utils import cache as cache_mod


# ===== 1) 不同 provider → 不同 key =====

def test_cache_key_differs_by_provider():
    """不同 LLM provider 应生成不同 cache key（核心：避免跨 provider 污染）。"""
    k_kimi = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    k_minimax = cache_mod.cache_key("q", 3, 1.0, provider="minimax")
    k_glm = cache_mod.cache_key("q", 3, 1.0, provider="glm")
    k_anthropic = cache_mod.cache_key("q", 3, 1.0, provider="anthropic")

    # 任两个不同 provider 的 key 必须不同
    keys = [k_kimi, k_minimax, k_glm, k_anthropic]
    assert len(set(keys)) == 4, (
        f"4 个不同 provider 应生成 4 个不同 key, 实际 {len(set(keys))} 个 unique: {keys}"
    )


# ===== 2) 默认 provider (None) → "default" 占位 =====

def test_cache_key_default_provider_is_deterministic():
    """无 provider (None) 时, 同 query + 同参数 → 同 key（向后兼容, 稳定）。"""
    k1 = cache_mod.cache_key("q", 3, 1.0)  # provider=None
    k2 = cache_mod.cache_key("q", 3, 1.0, provider=None)
    k3 = cache_mod.cache_key("q", 3, 1.0)  # 再次不传
    assert k1 == k2 == k3, (
        f"无 provider 时 cache_key 应稳定, 实际 {k1} != {k2} != {k3}"
    )


def test_cache_key_default_differs_from_specific_provider():
    """默认 (None) provider 的 key 应与具体 provider 的 key 不同。"""
    k_default = cache_mod.cache_key("q", 3, 1.0)  # provider=None → "default"
    k_kimi = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    assert k_default != k_kimi, (
        f"默认 provider key 应与 kimi key 不同, 实际都是 {k_default}"
    )


# ===== 3) 同 provider + 同 query → 相同 key =====

def test_cache_key_same_provider_same_inputs_same_key():
    """同 provider + 同其他参数 → 相同 key（hash 稳定性）。"""
    k1 = cache_mod.cache_key("transformer", 3, 1.0, provider="kimi")
    k2 = cache_mod.cache_key("transformer", 3, 1.0, provider="kimi")
    assert k1 == k2


# ===== 4) 签名包含 provider 参数 =====

def test_cache_key_signature_accepts_provider():
    """cache_key 签名应包含 provider 参数（默认 None, 向后兼容）。"""
    sig = inspect.signature(cache_mod.cache_key)
    assert "provider" in sig.parameters, (
        f"cache_key 签名应包含 'provider' 参数, 实际参数: {list(sig.parameters)}"
    )
    # 默认值必须是 None（向后兼容）
    assert sig.parameters["provider"].default is None, (
        f"cache_key(provider=...) 默认值应为 None, 实际 {sig.parameters['provider'].default}"
    )


# ===== 5) 异构 case sensitivity =====

def test_cache_key_provider_is_case_sensitive():
    """provider 大小写敏感 (与 config.get_provider_config 一致)。"""
    k_lower = cache_mod.cache_key("q", 3, 1.0, provider="kimi")
    k_upper = cache_mod.cache_key("q", 3, 1.0, provider="KIMI")
    assert k_lower != k_upper, (
        "provider 区分大小写 (config.get_provider_config 用 lower() 规范化, "
        "cache_key 自身保持原始大小写)"
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
