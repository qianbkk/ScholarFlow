"""
backend.agents.services — 可选依赖注入 (P1-1 审计迁移)

AAA.txt P1-1 / X.md §2.2 报告:
  8 个 agent 节点全部直接 import backend.utils.llm_client.call_llm,
  无法注入测试替身, 只能靠 LLM_MOCK=true 全局切换, 难以测
  "某个节点 LLM 失败 + 另一节点成功" 等精细场景.

本模块提供"渐进式"依赖注入:
  1. NodeServices dataclass 持有 LLM / SS / OA 三个核心依赖的引用
  2. default_services() 返回当前进程全局默认 (生产用, 等价于旧行为)
  3. 每个节点函数签名升级为 (state, services=None), services=None 时
     自动 fallback 到 default_services(). 旧调用方零修改.
  4. 测试可构造 MockServices(call_llm=MockLLM(...)) 注入, 精确模拟.

本轮 (R10.5 P1-1) 落地:
  - 新建本文件 (NodeServices + default_services + 一个 MockServices 示例)
  - rank_node + synthesize_node 加 services 参数 (最容易出错的两节点优先)
  - 其他节点 R10.6+ 跟进 (避免一次性 8 文件改动, 风险/收益比不划算)

后续演进 (R10.6+):
  - 把 LLM_MOCK 环境变量分支也收敛到 default_services() 内, 一处切换
  - 8 节点全部加 services 参数, 统一注入测试
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable


# ===== Protocol: 让测试可用任意 duck-typed 替身 =====

@runtime_checkable
class LLMClientProto(Protocol):
    """call_llm 协议的最小接口 (向后兼容)."""

    async def __call__(
        self,
        prompt: str,
        task_type: str = "complex_reason",
        system: str = "You are a helpful academic research assistant.",
        max_tokens: int = 2000,
        json_mode: bool = False,
        provider: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> tuple[str, dict]:
        """Return (text, usage_info). usage 至少含 model / cost_usd / input_tokens / output_tokens."""
        ...


@runtime_checkable
class SearchClientProto(Protocol):
    """semantic_scholar.search_papers / openalex.search_papers 的最小接口."""

    async def __call__(self, query: str, limit: int = 50) -> list:
        ...


# ===== 容器 =====

@dataclass
class NodeServices:
    """节点级依赖容器. None 表示"用默认" (向后兼容)."""
    llm: Optional[Callable[..., Awaitable[tuple[str, dict]]]] = None
    ss_search: Optional[Callable[..., Awaitable[list]]] = None
    oa_search: Optional[Callable[..., Awaitable[list]]] = None


_default_services_singleton: Optional[NodeServices] = None


def default_services() -> NodeServices:
    """进程级默认 services. 每次 lazy import 模块级 call_llm / ss / oa.

    R10.5 P1-1 实现说明:
      - 不在模块导入时直接 import backend.utils.llm_client 等 (避免循环 import).
      - **不缓存**: 每次调用都重新查模块属性. 这样测试用
        `patch.object(synthesis_agent, "call_llm", mock)` 才能生效 (否则我们
        缓存的引用是旧值). 性能开销可忽略 (一次 dict lookup).
      - LLM_MOCK / API_MOCK 等环境变量在原始模块层 (call_llm 内部) 仍生效,
        跟旧行为完全一致.
    """
    from backend.utils import llm_client as _llm
    from backend.api import semantic_scholar as _ss
    from backend.api import openalex as _oa
    return NodeServices(
        llm=_llm.call_llm,
        ss_search=_ss.search_papers,
        oa_search=_oa.search_papers,
    )


def reset_default_services() -> None:
    """保留 API 兼容 (旧版本有缓存). 当前实现无缓存, noop."""
    pass


# ===== Mock 实现示例 (给测试参考) =====

class MockLLM:
    """可预设响应的 mock LLM 替身.

    用法:
        mock = MockLLM(responses=["论文1", "论文2", "论文3"])
        services = NodeServices(llm=mock)
        await rank_node(state, services=services)
    """

    def __init__(self, responses: list[tuple[str, dict]] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict] = []

    async def __call__(
        self,
        prompt: str,
        task_type: str = "complex_reason",
        system: str = "",
        max_tokens: int = 2000,
        json_mode: bool = False,
        provider: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> tuple[str, dict]:
        self.calls.append({
            "prompt": prompt,
            "task_type": task_type,
            "system": system,
            "max_tokens": max_tokens,
            "json_mode": json_mode,
            "provider": provider,
        })
        if not self._responses:
            return "", {"model": "mock", "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
        return self._responses.pop(0)
