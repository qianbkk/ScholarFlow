"""
backend.utils.runtime_mode
==========================

R10.5.20: Runtime mode 集中管理 (取代 env 启动时锁定的 LLM_MOCK / API_MOCK).

历史:
- backend/config.py L23-24 LLM_MOCK / API_MOCK 是 os.getenv() 启动时读取,
  运行时不能改. 用户反映"Mock / Real 模式只文档有, 前端没切".
- 旧设计: 用户想从 Mock 切到 Real 必须重启后端, 体验差.

新设计:
- 加 _runtime_mode dict, 业务函数查 _runtime_mode 后 fallback env.
- 加 POST /api/v1/admin/runtime-mode 端点 (OPEN_MODE 或 admin 角色限定),
  让前端可以运行时切换.
- 单 worker 内存状态, 跟熔断器 (circuit_breaker.py) 同样的进程级单例模型,
  文档化: 4 worker 部署下每个 worker 独立, 用户切到 Mock 后只有 1/N 请求
  走 mock, 其余继续真. 短期接受, R11+ 切到 Redis.

API:
- GET /api/v1/admin/runtime-mode → {mode: 'mock'|'real', source: 'env'|'runtime'}
- POST /api/v1/admin/runtime-mode body {mode: 'mock'|'real'} → 切模式

环境优先级:
- _runtime_mode['mode'] = 'mock' if 设了
- 否则读 env LLM_MOCK || API_MOCK
- 否则 default = 'real' (生产推荐)

调用示例 (业务函数):
    from backend.utils.runtime_mode import is_runtime_mock
    if is_runtime_mock():
        return mock_data()
    else:
        return await real_api_call()

R10.5.25 (深度审计 §8): 加 RuntimeProfile enum + 集中状态表.
旧设计 5 开关 (OPEN_MODE / LLM_MOCK / API_MOCK / ENVIRONMENT / runtime override)
各自从 env 读, 容易语义错配. 新增 RuntimeProfile 把"开发/演示/生产"3 个
典型场景预定义为单一开关, 运维只关心 1 个 env (RUNTIME_PROFILE), runtime
override 仍可临时覆盖 mock/real.

未做 (commit message 标注): RuntimeProfile 暂仅做"加 enum + 启动期打印
当前 profile 名字", 不强制互斥检查. R11+ 真正落实"config 统一由
RuntimeProfile 决定, 其他 env 失效" 的大重构.
"""
from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Literal

logger = logging.getLogger(__name__)


# ===== R10.5.25: RuntimeProfile enum =====
class RuntimeProfile(str, Enum):
    """集中化的运行时 profile, 涵盖 5 开关最常见组合.

    实际 5 开关 (OPEN_MODE / LLM_MOCK / API_MOCK / ENVIRONMENT / runtime
    override) 仍独立工作, 此 enum 只在 startup 打印 + R11+ 强制互斥时
    才用作参考.

    Profile 定义:
      DEV_MOCK    — 本地开发, OPEN_MODE=true + LLM_MOCK=true + API_MOCK=true.
                    一键跑通, 不需任何 key.
      DEV_REAL    — 本地开发用真 LLM (有 MiniMax/Kimi/GLM key), OPEN_MODE=true.
                    演示/开发用, 鉴权不挡.
      OPEN_DEMO   — 多用户 demo, OPEN_MODE=false (强制 auth), LLM_MOCK=true.
                    演示部署: 用户能注册, 但 LLM 走 mock 节省成本.
      PRODUCTION  — 正式部署, OPEN_MODE=false + LLM_MOCK=false + API_MOCK=false.
                    全部走真 API, 鉴权强制, 配置完整.
    """
    DEV_MOCK = "dev_mock"
    DEV_REAL = "dev_real"
    OPEN_DEMO = "open_demo"
    PRODUCTION = "production"


def detect_runtime_profile() -> RuntimeProfile:
    """R10.5.25: 根据当前 5 开关推断 RuntimeProfile.

    推断规则 (按优先级):
      1. PRODUCTION: OPEN_MODE=false + LLM_MOCK=false + API_MOCK=false
      2. OPEN_DEMO:  OPEN_MODE=false + LLM_MOCK=true (允许 API_MOCK 任意)
      3. DEV_REAL:   OPEN_MODE=true  + LLM_MOCK=false
      4. DEV_MOCK:   OPEN_MODE=true  + LLM_MOCK=true (兜底)
    """
    from backend.config import LLM_MOCK, API_MOCK
    # 延迟 import 避免循环
    from backend.auth.dependencies import OPEN_MODE

    if not OPEN_MODE and not LLM_MOCK and not API_MOCK:
        return RuntimeProfile.PRODUCTION
    if not OPEN_MODE and LLM_MOCK:
        return RuntimeProfile.OPEN_DEMO
    if OPEN_MODE and not LLM_MOCK:
        return RuntimeProfile.DEV_REAL
    return RuntimeProfile.DEV_MOCK


# 进程级 runtime 模式覆盖 (env 之外的前端切换). None = 走 env 兜底.
_runtime_mode_override: dict[str, str] = {"mode": "auto"}


def get_runtime_mode() -> Literal["mock", "real", "auto"]:
    """返回当前生效的 runtime 模式.

    Returns:
        "mock": 前端切到了 mock (或 env 强制 mock)
        "real": 前端切到了 real (或 env 强制 real)
        "auto": 没显式设置, 走 config 默认 (通常 = real 但兼容 LLM_MOCK=true 自动 mock)
    """
    return _runtime_mode_override["mode"]  # type: ignore[return-value]


def set_runtime_mode(mode: Literal["mock", "real", "auto"]) -> None:
    """前端调 admin API 设的. 'auto' = 恢复 env 行为."""
    _runtime_mode_override["mode"] = mode
    logger.info(f"[runtime_mode] override set to: {mode}")


def is_runtime_mock() -> bool:
    """业务函数查这个, 判断当前是否走 mock.

    优先级:
      1. _runtime_mode_override (前端 /admin/runtime-mode 切)
      2. env LLM_MOCK || API_MOCK (config.py 启动时)
      3. 默认 False (走真实 API)
    """
    override = _runtime_mode_override.get("mode", "auto")
    if override == "mock":
        return True
    if override == "real":
        return False
    # auto: 走 env
    llm_mock = os.getenv("LLM_MOCK", "true").lower() in ("1", "true", "yes")
    api_mock = os.getenv("API_MOCK", "true").lower() in ("1", "true", "yes")
    return llm_mock or api_mock
