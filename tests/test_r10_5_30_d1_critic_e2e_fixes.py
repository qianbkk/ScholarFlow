"""D1 (P0-3 + P0-4) 修复验证: critic_agent kwargs + e2e 用 stream 端点.

P0-3: critic_agent 旧版用 call_llm(model=...) + temperature=0.3, 这 2 个都是
call_llm 不接受的 kwarg (call_llm 只接 model_override, 无 temperature),
导致 TypeError + 10 次重试. 改用 model_override + task_type='fast' + json_mode.

P0-4: e2e 7 fail 全部是 /search 同步 60s timeout. 改用 /api/v1/search/stream
(SSE, 480s) + 包装 _FakeResponse 让 r.status_code / r.json() 仍可用.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ===== P0-3: critic_agent 不再传 model= / temperature =====
def test_critic_agent_no_invalid_kwargs():
    """critic_agent.py 调 call_llm 时不能用 'model=' / 'temperature=' kwarg.
    call_llm 签名是 (prompt, task_type, system, max_tokens, json_mode, provider,
    model_override) — 没有 model, 没有 temperature. 旧版传这 2 个会
    TypeError 触发 10 次重试, 跑完一次 critic 评审 30+ 秒, 8 节点流水线
    撞 60s sync timeout."""
    src = (ROOT / "backend" / "agents" / "critic_agent.py").read_text(encoding="utf-8")
    # 不能有 model= 或 temperature= 在 call_llm 调用块里
    idx = src.find("await call_llm(")
    assert idx > 0
    # 只看 call_llm 实际参数行 (找到 call_llm( 后的 \n) — 用 ast 解析避免注释假阳性
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # 用 ast.unparse 检查函数名
            func = ast.unparse(node.func) if hasattr(ast, "unparse") else None
            if func and ("call_llm" in func):
                # 检查 kwarg 名
                kwarg_names = [kw.arg for kw in node.keywords]
                assert "model" not in kwarg_names, (
                    f"critic_agent 调 call_llm 传了 model= (D1 P0-3 没生效). "
                    f"实际 kwargs: {kwarg_names}"
                )
                assert "temperature" not in kwarg_names, (
                    f"critic_agent 调 call_llm 传了 temperature= (D1 P0-3 没生效). "
                    f"实际 kwargs: {kwarg_names}"
                )
                assert "model_override" in kwarg_names, (
                    f"critic_agent 应改用 model_override= (D1 P0-3). "
                    f"实际 kwargs: {kwarg_names}"
                )
                return  # 找到 call_llm 调用就返回
    raise AssertionError("critic_agent.py 没找到 call_llm(...) 调用")


def test_critic_agent_uses_json_mode():
    """critic 评审需要结构化 JSON 输出, 必须传 json_mode=True 让 call_llm
    走 _call_anthropic_compatible 的 response_format 路径."""
    src = (ROOT / "backend" / "agents" / "critic_agent.py").read_text(encoding="utf-8")
    idx = src.find("await call_llm(")
    assert idx > 0
    window = src[idx:idx + 800]
    assert "json_mode=True" in window, (
        "critic_agent 调 call_llm 缺 json_mode=True (D1 P0-3 修没生效)"
    )


# ===== P0-4: e2e 改用 stream 端点 =====
def test_e2e_uses_stream_endpoint():
    """e2e _post_search 改用 /api/v1/search/stream (480s SSE) 而非 /api/v1/search
    (60s 同步). 旧版 7 fail 全部是 504 同步 timeout."""
    src = (ROOT / "tests" / "test_full_pipeline_e2e.py").read_text(encoding="utf-8")
    # 必须有 c.stream 或 streaming 调用
    assert "c.stream(" in src or "client.stream(" in src, (
        "e2e 改用 stream 端点 (D1 P0-4 修没生效)"
    )
    # 必须包含 _FakeResponse 包装类 (让 r.status_code / r.json() 仍可用)
    assert "_FakeResponse" in src, "e2e 缺 _FakeResponse 包装类 (stream done 转 Response)"
    # 必须用 /api/v1/search/stream 路径
    assert "/api/v1/search/stream" in src, "e2e 没指向 /api/v1/search/stream"
    # 不能再调 POST /api/v1/search
    assert '"/api/v1/search"' not in src and "'/api/v1/search'" not in src, (
        "e2e 仍调 POST /api/v1/search (D1 P0-4 修没生效)"
    )
