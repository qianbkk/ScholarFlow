"""
ScholarFlow 配置文件
统一从环境变量加载配置，所有字段都有默认值（缺失时优雅降级）。
"""
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(override=False)  # Round 5 M-2: shell env 优先, .env 仅作默认值.
                                # 之前 override=True 会静默吞掉 K8s/Docker secret
                                # 注入的 ENV (Secret 走 env 注入, .env 不存在时反而是 fallback).
                                # override=False 让 K8s ConfigMap/Secret、docker -e、
                                # CI workflow env 等所有"外部注入"成为 source of truth,
                                # .env 仅在本地开发时提供默认值。


# ===== 离线运行 / Mock 模式 =====
# LLM_MOCK=true 时，llm_client 返回预置响应，不真正调用外部 API
# API_MOCK=true 时，学术 API 客户端返回预置论文数据
# 默认开启 mock（无网络环境可跑通）；有网络时可设为 false
LLM_MOCK = os.getenv("LLM_MOCK", "true").lower() in ("1", "true", "yes")
API_MOCK = os.getenv("API_MOCK", "true").lower() in ("1", "true", "yes")

# 如果没有任何 LLM key，自动开启 mock
_has_any_llm_key = any([
    os.getenv("KIMI_API_KEY", ""),
    os.getenv("GLM_API_KEY", ""),
    os.getenv("MiniMax_API_KEY", ""),
    os.getenv("ANTHROPIC_API_KEY", ""),
])
if not _has_any_llm_key:
    LLM_MOCK = True
    logger.warning("[config] No LLM API key detected. LLM_MOCK auto-enabled.")


# ===== LLM Provider 路由配置 =====

# Anthropic 官方
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

# Kimi / Moonshot
KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/anthropic")
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-k2.5")
KIMI_FAST_MODEL = os.getenv("KIMI_FAST_MODEL", "kimi-k2.5")

# GLM / 智谱
GLM_API_KEY = os.getenv("GLM_API_KEY", "")
GLM_BASE_URL = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
GLM_MODEL = os.getenv("GLM_MODEL", "glm-4.6")
GLM_FAST_MODEL = os.getenv("GLM_FAST_MODEL", "glm-4.6-air")

# MiniMax
MiniMax_API_KEY = os.getenv("MiniMax_API_KEY", "")
MiniMax_BASE_URL = os.getenv("MiniMax_BASE_URL", "https://api.minimaxi.com/anthropic")
MiniMax_MODEL = os.getenv("MiniMax_MODEL", "MiniMax-M3")
MiniMax_FAST_MODEL = os.getenv("MiniMax_FAST_MODEL", "MiniMax-M2.7")

# DeepSeek（兼容 OpenAI 协议）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# ===== 学术 API =====
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "scholar@flow.ai")

# ===== 运行时配置 =====
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "kimi").lower()
BUDGET_LIMIT_USD = float(os.getenv("BUDGET_LIMIT_USD", "2.0"))
MAX_SEARCH_ITERATIONS = int(os.getenv("MAX_SEARCH_ITERATIONS", "3"))

# ===== Router 决策阈值（条件路由：决定 rank 之后是 refine 还是 synthesize）=====
# 当 top5 平均相关性达到阈值且论文数达到阈值时，判定结果质量足够直接出报告。
ROUTER_QUALITY_THRESHOLD_REL = float(os.getenv("ROUTER_QUALITY_THRESHOLD_REL", "7.0"))
ROUTER_QUALITY_THRESHOLD_PAPERS = int(os.getenv("ROUTER_QUALITY_THRESHOLD_PAPERS", "15"))
# 剩余预算低于 (budget * (1 - margin)) 时，强制走 synthesize 避免耗尽预算。
ROUTER_BUDGET_SAFETY_MARGIN = float(os.getenv("ROUTER_BUDGET_SAFETY_MARGIN", "0.3"))


def get_provider_config(
    provider: str | None = None,
    *,
    strict: bool = True,
) -> dict:
    """
    返回当前 provider 的 base_url / api_key / model / fast_model 字典。

    R8 修复 (reviewer feedback 3.2 - provider 语义错误):
      旧实现: 未知 provider 静默回退到 kimi — 把"根本不存在的 provider"伪装成
      "合法 provider", 属于 correctness bug (错误地成功)。
      新实现:
        - strict=True (默认): 未知 provider 直接 raise ValueError, fail loud
        - strict=False: 旧行为回退 (仅 /providers 端点等需要"列举所有合法 + 未配置"
          的场景才用, 显式 opt-in)
      caller 端:
        - 内部 LLM 调用路径 (llm_client.py): 默认 strict, 任意传错会立即 500 +
          真实错误信息, 而非"用 kimi 跑出莫名其妙结果"
        - /providers 端点: 显式 strict=False 列举所有合法 provider
          (含未启用 / 未配 key)
    """
    provider = (provider or LLM_PROVIDER).lower()

    configs = {
        "kimi": {
            "base_url": KIMI_BASE_URL,
            "api_key": KIMI_API_KEY,
            "model": KIMI_MODEL,
            "fast_model": KIMI_FAST_MODEL,
            "auth_type": "bearer",
            "enabled": bool(KIMI_API_KEY),
        },
        "glm": {
            "base_url": GLM_BASE_URL,
            "api_key": GLM_API_KEY,
            "model": GLM_MODEL,
            "fast_model": GLM_FAST_MODEL,
            "auth_type": "bearer",
            "enabled": bool(GLM_API_KEY),
        },
        "minimax": {
            "base_url": MiniMax_BASE_URL,
            "api_key": MiniMax_API_KEY,
            "model": MiniMax_MODEL,
            "fast_model": MiniMax_FAST_MODEL,
            "auth_type": "bearer",
            "enabled": bool(MiniMax_API_KEY),
        },
        "anthropic": {
            "base_url": ANTHROPIC_BASE_URL,
            "api_key": ANTHROPIC_API_KEY,
            "model": "claude-sonnet-4-6",
            "fast_model": "claude-haiku-4-5-20251001",
            "auth_type": "x-api-key",
            "enabled": bool(ANTHROPIC_API_KEY),
        },
    }
    if provider not in configs:
        if strict:
            raise ValueError(
                f"unknown LLM provider: {provider!r} "
                f"(known: {sorted(configs.keys())})"
            )
        # strict=False: 旧回退行为, 仅 /providers 端点等列举场景使用
        return configs["kimi"]
    return configs[provider]
