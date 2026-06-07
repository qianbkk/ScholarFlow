"""
backend.api.services.providers
================================

LLM provider health-check, key verification, and request-time provider
resolution. Extracted from backend/main.py during the god-object refactor.

Surface (kept stable for tests):
  * _PROVIDER_META                 — public display metadata for /providers
  * _PROVIDER_HEALTH_CACHE         — {(ok: bool, ts: float)} 5-min TTL cache
  * _PROVIDER_HEALTH_TTL_SECONDS   — float, 300s
  * _verify_provider_key(pid) -> bool
  * _get_providers_with_keys()     — list of dicts for frontend selector
  * _refresh_provider_health_cache() — background coroutine
  * _resolve_provider(provider) -> str  — raises HTTPException(400) if invalid
"""
from __future__ import annotations

import logging
import time as _time
from typing import Optional

from fastapi import HTTPException

from backend.config import (
    LLM_PROVIDER,
    DEEPSEEK_API_KEY,
    get_provider_config,
)

logger = logging.getLogger(__name__)


# ===== Provider 路由元数据（用户可选 LLM）=====
# 给前端 /providers 端点用的展示元数据。
# has_key 来自对应 *_API_KEY 环境变量 — 没有 key 的 provider 不在选择列表里。
# DeepSeek 走 OpenAI 协议（不走 get_provider_config），单独处理。
#
# R10 (M-16): 顺序按"演示默认 → 备选"排 (minimax → kimi → glm → anthropic → deepseek).
# 注意: 5 个 provider 全部保留 — 实际项目演示只需要 MiniMax 即可,
# 但其他 provider 是"用户可能切换"的产品选项, 不是冗余.
# 不要删 — 即便当前 .env 只配了 MiniMax key, 删了反而限制灵活性.
_PROVIDER_META = {
    "minimax": {
        "name": "MiniMax",
        "flagship_model": "MiniMax-M3",
        "fast_model": "MiniMax-M2.7",
    },
    "kimi": {
        "name": "Kimi (Moonshot)",
        "flagship_model": "kimi-k2.5",
        "fast_model": "kimi-k2.5",
    },
    "glm": {
        "name": "GLM (智谱)",
        "flagship_model": "glm-4.6",
        "fast_model": "glm-4.6-air",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "flagship_model": "claude-sonnet-4-6",
        "fast_model": "claude-haiku-4-5-20251001",
    },
    "deepseek": {
        "name": "DeepSeek",
        "flagship_model": "deepseek-reasoner",
        "fast_model": "deepseek-chat",
    },
}


# ===== Provider 健康检查缓存（key 真实可用性，非仅 env 非空）=====
# 用户在 .env 填了 Kimi/GLM key 但实际可能 401 失效。仅检查 env 非空会让
# /providers 返回误导性的 has_key=true，前端选择后真实调用失败 → 静默
# fallback 到 mock，用户看到"当前为 mock 模式"。这里在 lifespan + 定期
# 用最小 API 调用 (max_tokens=1) 验证 key, 缓存结果。
_PROVIDER_HEALTH_CACHE: dict[str, tuple[bool, float]] = {}
_PROVIDER_HEALTH_TTL_SECONDS = 300.0  # 5 min — 比 startup 一次更可靠


async def _verify_provider_key(provider_id: str) -> bool:
    """对单个 provider 做最小 API 调用验证 key 真实有效。

    Anthropic 协议: messages.create(max_tokens=1, 1 token prompt)
    OpenAI 协议 (DeepSeek): chat.completions.create(max_tokens=1)

    Returns:
        True  if API 调用成功 (任意 content / finish_reason)
        False if 401/403/网络错误/超时
    """
    if provider_id == "deepseek":
        try:
            from openai import AsyncOpenAI
            from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
            if not DEEPSEEK_API_KEY:
                return False
            client = AsyncOpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
                timeout=10.0,
            )
            resp = await client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=1,
                messages=[{"role": "user", "content": "ok"}],
            )
            return bool(resp.choices)
        except Exception:
            return False
    else:
        try:
            import anthropic  # noqa: F401 — 验证 anthropic SDK 可导入
            from backend.utils.llm_client import _get_anthropic_client
            client = _get_anthropic_client(provider_id)
            if client is None:
                return False
            # Anthropic SDK 不暴露 ping, 用最小 messages.create 验证
            # 选 fast_model (更快更便宜)
            cfg = get_provider_config(provider_id)
            fast_model = cfg.get("fast_model") or cfg.get("model", "")
            if not fast_model:
                return False
            resp = await client.messages.create(
                model=fast_model,
                max_tokens=1,
                messages=[{"role": "user", "content": "."}],
            )
            # 任意正常 stop_reason 都算通过 (包括 end_turn/max_tokens/refusal)
            return getattr(resp, "stop_reason", None) is not None
        except Exception:
            return False


def _get_providers_with_keys() -> list[dict]:
    """返回所有可用的 provider 列表（含 has_key 状态）。

    has_key 语义:
      * env var 非空 且 健康检查最近一次通过 → True
      * env var 为空 或 健康检查失败 → False
      * 健康检查尚未运行 (启动几秒内) → 用 env 非空作 optimistic 估计

    健康检查在 lifespan 启动时跑一次，之后每 5 分钟刷新一次。
    """
    out: list[dict] = []
    for pid, meta in _PROVIDER_META.items():
        # 1) 基础检查：env var 是否配置
        if pid == "deepseek":
            env_key_present = bool(DEEPSEEK_API_KEY)
        else:
            cfg = get_provider_config(pid)
            env_key_present = bool(cfg.get("enabled", False))

        # 2) 健康检查缓存（如果最新）
        cached = _PROVIDER_HEALTH_CACHE.get(pid)
        if cached and (_time.time() - cached[1]) < _PROVIDER_HEALTH_TTL_SECONDS:
            verified = cached[0]
        else:
            verified = None  # 未检查 或 缓存过期

        # 3) 决定 has_key:
        #    - 缓存有效 → 用缓存
        #    - 缓存无效/无 → 启动后用 env 估计；启动前 (lifespan 未跑完) 总是 None
        if verified is not None:
            has_key = env_key_present and verified
        else:
            # 启动乐观估计：env 非空就 True（但前端可加 has_verified 字段）
            has_key = env_key_present

        out.append({
            "id": pid,
            "name": meta["name"],
            "flagship_model": meta["flagship_model"],
            "fast_model": meta["fast_model"],
            "has_key": has_key,
            "verified": verified,  # True/False/None (None = 未检查)
        })
    return out


async def _refresh_provider_health_cache() -> None:
    """后台任务：刷新所有 provider 的真实 key 可用性。"""
    pids = list(_PROVIDER_META.keys())
    for pid in pids:
        try:
            ok = await _verify_provider_key(pid)
            _PROVIDER_HEALTH_CACHE[pid] = (ok, _time.time())
            logger.info(f"[providers] {pid} verified={ok}")
        except Exception as e:
            _PROVIDER_HEALTH_CACHE[pid] = (False, _time.time())
            logger.warning(f"[providers] {pid} verify failed: {e}")


def _resolve_provider(provider: Optional[str]) -> str:
    """解析并校验 provider；合法且有 key 则返回小写 id，否则 raise 400。

    规则：
      * None 或空字符串 → 默认 LLM_PROVIDER（来自 .env）— **前提是默认 provider 有 key**
        否则也 raise (避免默认 provider 静默回退)
      * 在 *有 key 的* provider 列表里 → 返回该 id
      * 其他 → 400 (含可用的 provider 列表)

    R8.2 修复 (reviewer feedback 3.2 - 旧实现 valid_ids 不过滤 has_key):
      旧实现: valid_ids = {p["id"] for p in candidates} 把"名字合法但 has_key=False"
      的 provider 也算 valid, 然后 llm_client 看到 enabled=False 会悄悄退化成 mock
      ("用户选了 provider X, 实际跑的是 mock Y" — 错误地成功)
      新实现: valid_ids = {p["id"] for p in candidates if p["has_key"]} 严格过滤
    """
    candidates = _get_providers_with_keys()
    valid_ids = {p["id"] for p in candidates if p["has_key"]}
    if not provider:
        default = LLM_PROVIDER.lower()
        if default not in valid_ids:
            raise HTTPException(
                status_code=400,
                detail=f"默认 provider {default!r} 无可用 key. "
                       f"请在 .env 配 *_API_KEY 或显式传 provider. "
                       f"可用: {sorted(valid_ids)}",
            )
        return default
    provider = provider.strip().lower()
    if provider not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 provider: {provider!r}. 可用: {sorted(valid_ids)}",
        )
    return provider
