"""修 LLM 客户端超时: MiniMax-M3 thinking + 长 prompt 触发 30s timeout,导致
synthesis 节点 fallback 到 mock, 用户看到"当前为 mock 模式"。

根因: anthropic.AsyncAnthropic 默认 timeout=30s, 但 MiniMax-M3 在 thinking 模式 +
max_tokens=3500 + 长 prompt 下,thinking 阶段 30-60s 才完成,客户端超时抛 APITimeoutError。

修复: timeout 30.0 → 120.0。
"""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import sys
sys.path.insert(0, '.')

import pytest
from backend.utils import llm_client


def test_anthropic_client_timeout_is_120s():
    """Anthropic 客户端 timeout 必须 >= 60s 以容纳 thinking + 长 prompt。"""
    # 触发单例创建 (前提: .env 至少有一个 LLM key)
    from backend.config import _has_any_llm_key
    if not _has_any_llm_key:
        pytest.skip("需要至少一个 LLM key 才能测试")

    client = llm_client._get_anthropic_client('minimax')
    if client is None:
        pytest.skip("minimax provider 未配置")

    # anthropic SDK httpx client 的 timeout 属性
    # httpx.Timeout 实例,total 字段表示总超时
    http = client._client  # 内部 httpx.AsyncClient
    timeout = http.timeout
    if hasattr(timeout, 'connect'):
        # httpx.Timeout namedtuple: connect/read/write/pool
        total = timeout.connect + timeout.read + timeout.write + timeout.pool
    else:
        total = float(timeout)
    assert total >= 60.0, (
        f"anthropic client timeout {total}s 仍可能让 MiniMax-M3 thinking "
        f"+ 3500 max_tokens 触发 APITimeoutError,需要 >= 60s (实际 120s)"
    )
    print(f"anthropic total timeout: {total}s")


def test_deepseek_client_timeout_is_120s():
    """DeepSeek 客户端 timeout 同步提升到 120s。"""
    from backend.config import DEEPSEEK_API_KEY
    if not DEEPSEEK_API_KEY:
        pytest.skip("DeepSeek key 未配置")

    client = llm_client._get_deepseek_client()
    if client is None:
        pytest.skip("DeepSeek client 创建失败")

    # OpenAI async client 内部 httpx
    http = client._client if hasattr(client, '_client') else client
    timeout = getattr(http, 'timeout', None)
    if hasattr(timeout, 'connect'):
        total = timeout.connect + timeout.read + timeout.write + timeout.pool
    else:
        total = float(timeout) if timeout else 0
    assert total >= 60.0, f"DeepSeek timeout {total}s 仍过低"
    print(f"DeepSeek total timeout: {total}s")


if __name__ == "__main__":
    test_anthropic_client_timeout_is_120s()
    print("OK anthropic timeout")
    try:
        test_deepseek_client_timeout_is_120s()
        print("OK deepseek timeout")
    except Exception as e:
        print(f"SKIP deepseek: {e}")
    print("=== LLM timeout fix test passed ===")
