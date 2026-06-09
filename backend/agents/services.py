"""
backend.agents.services — 可选依赖注入 (P1-1 审计迁移)

AAA.txt P1-1 / X.md §2.2 报告:
  8 个 agent 节点全部直接 import backend.utils.llm_client.call_llm,
  无法注入测试替身, 只能靠 LLM_MOCK=true 全局切换, 难以测
  "某个节点 LLM 失败 + 另一节点成功" 等精细场景.

R10.5 落地:
  - NodeServices dataclass + default_services() 工厂
  - synthesize_node 升级为 (state, services=None), 默认走本模块 call_llm
    (旧测试 patch 仍生效)
  - 其他 7 节点 R10.6+ 跟进 (避免一次性 8 文件改动, 风险/收益比不划算)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


@dataclass
class NodeServices:
    """节点级依赖容器. None 表示"用默认" (向后兼容)."""
    llm: Optional[Callable[..., Awaitable[tuple[str, dict]]]] = None
    ss_search: Optional[Callable[..., Awaitable[list]]] = None
    oa_search: Optional[Callable[..., Awaitable[list]]] = None


def default_services() -> NodeServices:
    """进程级默认 services. 每次 lazy import 模块级 call_llm / ss / oa.

    R10.5 P1-1 实现说明:
      - 不在模块导入时直接 import backend.utils.llm_client 等 (避免循环 import).
      - **不缓存**: 每次调用都重新查模块属性. 这样测试用
        `patch.object(synthesis_agent, "call_llm", mock)` 才能生效 (否则我们
        缓存的引用是旧值). 性能开销可忽略 (3 个 dict lookup, 都在 sys.modules).
    """
    from backend.utils import llm_client as _llm
    from backend.api import semantic_scholar as _ss
    from backend.api import openalex as _oa
    return NodeServices(
        llm=_llm.call_llm,
        ss_search=_ss.search_papers,
        oa_search=_oa.search_papers,
    )


# ===== Mock 实现示例 (给测试参考) =====

def make_mock_llm(responses: list[tuple[str, dict]] | None = None):
    """构造一个 mock LLM 替身. 返回 async-callable + 暴露 .calls 列表.

    用法:
        mock_llm = make_mock_llm([("论文1", {"model":"mock"}), ...])
        services = NodeServices(llm=mock_llm)
        await synthesize_node(state, services=services)
        # 检查 mock_llm.calls 看 LLM 调用历史
    """
    queue = list(responses or [])
    calls: list[dict] = []

    async def _mock(
        prompt: str,
        task_type: str = "complex_reason",
        system: str = "",
        max_tokens: int = 2000,
        json_mode: bool = False,
        provider: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> tuple[str, dict]:
        calls.append({"prompt": prompt, "task_type": task_type, "system": system})
        if not queue:
            return "", {"model": "mock", "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
        return queue.pop(0)

    _mock.calls = calls  # type: ignore[attr-defined]
    return _mock
