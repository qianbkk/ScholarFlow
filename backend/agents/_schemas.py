"""backend.agents._schemas
========================

R10.5.47 (P1 LLM 输出韧性): Pydantic v2 结构化输出 schema.

审计 #8: query_decompose + ranker_agent 用 LLM 输出 JSON, 轻量模型
(MiniMax/Kimi-fast) 经常 JSON 格式崩溃 (缺引号 / 多余逗号 / schema 字段缺失).
旧实现: 字符串扫描 + 字段类型检查 (脆弱, 5+ 字段全靠 dict.get + isinstance 兜底).
新实现: Pydantic v2 BaseModel 校验, 失败时 1 次重试 (prompt 加格式提示),
再失败走原有 fallback.

为什么不用 Instructor / Outlines:
- 这两个库需要特定 LLM client 集成, 加新依赖.
- 现状是直接调 Anthropic-compatible API, Pydantic v2 + JSON 解析已经够用.
- 复杂场景 (R11+ 多 provider) 再考虑 Instructor.

为什么 1 次重试不是更多:
- LLM 第二次还坏通常是真的格式错误, 重试浪费 token.
- 1 次重试 + 现有 fallback 兜底足够覆盖 99% case.
"""
from __future__ import annotations

from typing import Any, Optional, Literal

import logging
from pydantic import BaseModel, Field, RootModel, field_validator

logger = logging.getLogger(__name__)


# ===== query_decomposer 输出 schema =====

class ConstraintsModel(BaseModel):
    """R10.5.47: 4 维结构化约束 (venue / year_range / methods / datasets).

    字段全 Optional, 缺省 None. year_range 严格 [lo, hi] 列表 + 范围校验.
    """
    venues: Optional[list[str]] = None
    year_range: Optional[list[int]] = None
    methods: Optional[list[str]] = None
    datasets: Optional[list[str]] = None

    @field_validator("year_range")
    @classmethod
    def validate_year_range(cls, v):
        """[lo, hi] 2 个 int, 范围 [1900, 2100], lo <= hi. 失败抛 ValueError."""
        if v is None:
            return v
        if not isinstance(v, list) or len(v) != 2:
            raise ValueError("year_range must be [lo, hi] list of 2 items")
        try:
            lo, hi = int(v[0]), int(v[1])
        except (TypeError, ValueError):
            raise ValueError("year_range must contain ints")
        if not (1900 <= lo <= 2100 and 1900 <= hi <= 2100):
            raise ValueError("year_range out of [1900, 2100]")
        if lo > hi:
            raise ValueError("year_range lo > hi")
        return [lo, hi]


# query_type 字面量 (跟 query_decomposer._QUERY_TYPE_LIMITS 对齐)
QueryTypeLiteral = Literal[
    "simple", "survey", "method", "comparison", "latest", "default"
]


class DecomposeOutput(BaseModel):
    """R10.5.47: query_decomposer LLM 输出 schema.

    字段:
    - analysis: 1-2 句中文研究意图分析 (Optional)
    - query_type: 5 种 + default 兜底, 跟 _QUERY_TYPE_LIMITS 对齐
    - sub_queries: 1-20 个英文子查询, 自动过滤非 str / 空串 / len <= 3
    - key_terms: 关键术语列表 (Optional)
    - constraints: 4 维结构化约束 (Optional)

    Pydantic v2 校验失败 → ValidationError, 调用方决定 retry 还是 fallback.
    """
    analysis: Optional[str] = None
    query_type: QueryTypeLiteral = "default"
    # 字段类型 Any 让我们能接受 LLM 返回的 [str, int, null, ...] 混合,
    # clean_sub_queries validator 过滤出有效 str 元素.
    # 用 list[str] 严格类型会让 Pydantic 在 validator 跑之前就拒整个 list.
    sub_queries: list[Any] = Field(default_factory=list, max_length=20)
    key_terms: Optional[list[str]] = None
    constraints: Optional[ConstraintsModel] = None

    @field_validator("sub_queries")
    @classmethod
    def clean_sub_queries(cls, v: list) -> list[str]:
        """过滤非 str / 空串 / 长度 ≤ 3 的元素. 跟 query_decomposer 旧行为对齐."""
        return [
            s.strip() for s in v
            if isinstance(s, str) and len(s.strip()) > 3
        ]


# ===== ranker_agent 输出 schema =====

class PaperScore(BaseModel):
    """R10.5.47: 单篇论文 3 维分数 (relevance / consistency / authority)."""
    relevance: float = Field(ge=0.0, le=10.0, default=5.0)
    consistency: float = Field(ge=0.0, le=10.0, default=6.0)
    authority: float = Field(ge=0.0, le=10.0, default=5.0)


class RankBatchOutput(RootModel[dict[str, PaperScore]]):
    """R10.5.47: ranker_agent LLM 输出 schema.

    LLM 输出 {"1": {"relevance": 8.5, ...}, "2": {...}, ...} 形式
    (1-based 论文编号 → 3 维分数 dict).

    用 RootModel 让顶层就是 scores dict, 不用 .scores 二层访问.
    Pydantic v2 校验失败 → ValidationError, 调用方决定 retry 还是 fallback.
    """
    root: dict[str, PaperScore] = Field(default_factory=dict)


# ===== R10.5.51 (/simplify): 共享 Pydantic 解析 + retry helper =====

import asyncio
from backend.utils.llm_client import merge_usage_into_state as _merge_usage


def _strip_markdown_fence(text: str) -> str:
    """剥 LLM 常见的 ```json ... ``` markdown 围栏."""
    text = text.strip()
    if text.startswith("```"):
        # 找到第一个换行, 跳过 "```json" 或 "```"
        first_newline = text.find("\n")
        if first_newline > 0:
            text = text[first_newline + 1:]
        # 末尾 ``` 也剥掉
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


async def parse_with_retry_async(
    *,
    call_llm,
    prompt: str,
    schema: type[BaseModel],
    system: str,
    max_tokens: int,
    task_type: str,
    provider=None,
    timeout: float,
    retry_suffix: str,
    log_tag: str,
    base_usage: dict | None = None,
) -> tuple[Optional[BaseModel], Optional[dict]]:
    """R10.5.51: 共享 Pydantic + 1 次 retry 解析 (替换 query_decomposer / ranker_agent 内联重复).

    流程:
    1. 调 call_llm 拿 (text, usage)
    2. Pydantic v2 model_validate_json 尝试解析 (剥 markdown 围栏)
    3. 失败 → 1 次 retry: prompt 加 retry_suffix 提示, 重新调 LLM
    4. 仍失败 → 返 (None, last_usage) 让调用方走 fallback

    用法 (替换 query_decomposer / ranker_agent 内联 ~45 行):
        parsed_obj, usage = await parse_with_retry_async(
            call_llm=call_llm, prompt=prompt, schema=DecomposeOutput,
            system=SYSTEM + isolation_system_suffix(),
            max_tokens=500, task_type="complex_reason",
            provider=state.get("provider"), timeout=30.0,
            retry_suffix="⚠️ 上一轮输出 JSON 解析失败, ...",
            log_tag="query_decompose", base_usage=None,
        )

    Args:
        call_llm: backend.utils.llm_client.call_llm
        prompt: 完整 prompt (含 retry_suffix 由调用方拼)
        schema: Pydantic v2 BaseModel 子类
        system: system prompt
        max_tokens: LLM 输出 token 上限
        task_type: 任务类型 (影响模型选择)
        provider: LLM provider (kimi/glm/...); None 用 env 兜底
        timeout: LLM 调用超时 (秒)
        retry_suffix: 追加到 prompt 末尾的格式提示
        log_tag: 日志前缀 (e.g. "query_decompose")
        base_usage: 累加基准 usage (None 或前次调用的 usage)

    Returns:
        (parsed_model, final_usage) 成功
        (None, final_usage) 失败 (1 次重试后仍坏) — final_usage 含 base + retry 累加
    """
    # 1) 第一次调用
    try:
        text, usage = await asyncio.wait_for(
            call_llm(
                prompt,
                task_type=task_type,
                system=system,
                max_tokens=max_tokens,
                json_mode=True,
                provider=provider,
            ),
            timeout=timeout,
        )
    except Exception as first_exc:
        # R10.5.51: TimeoutError 必须向上传播 (Fix-P 节点级超时).
        # 其他异常 (网络/认证) 才静默吞, 走 fallback.
        if isinstance(first_exc, asyncio.TimeoutError):
            logger.warning(f"[{log_tag}] call_llm 第一次超时 ({timeout}s): {type(first_exc).__name__}")
            raise
        logger.warning(f"[{log_tag}] call_llm 第一次失败: {type(first_exc).__name__}")
        return None, base_usage

    # 2) Pydantic 校验
    cleaned = _strip_markdown_fence(text or "")
    try:
        return schema.model_validate_json(cleaned), usage
    except Exception as first_exc:
        err_count = getattr(first_exc, "error_count", lambda: 0)()
        logger.warning(
            f"[{log_tag}] Pydantic 校验失败, 尝试 1 次重试. "
            f"errors={err_count} exc={type(first_exc).__name__}"
        )

    # 3) Retry: 拼 retry_suffix 重新调用
    retry_prompt = prompt + "\n\n" + retry_suffix
    try:
        retry_text, retry_usage = await asyncio.wait_for(
            call_llm(
                retry_prompt,
                task_type=task_type,
                system=system,
                max_tokens=max_tokens,
                json_mode=True,
                provider=provider,
            ),
            timeout=timeout,
        )
    except Exception as second_exc:
        # R10.5.51: 同上, TimeoutError 必须向上传播.
        if isinstance(second_exc, asyncio.TimeoutError):
            logger.warning(f"[{log_tag}] retry 超时 ({timeout}s): {type(second_exc).__name__}")
            raise
        logger.warning(
            f"[{log_tag}] retry 也失败: {type(second_exc).__name__}: {str(second_exc)[:200]}"
        )
        # 累加 retry cost (即使没拿到 retry_usage, 用 base_usage 兜底)
        return None, _merge_usage({"model_usage": base_usage or {}}, {"model_usage": {}})

    # 4) 第二次校验
    retry_cleaned = _strip_markdown_fence(retry_text or "")
    final_usage = _merge_usage(
        {"model_usage": base_usage or {}},
        {"model_usage": retry_usage.get("model_usage", retry_usage) if isinstance(retry_usage, dict) else {}},
    )
    try:
        return schema.model_validate_json(retry_cleaned), final_usage
    except Exception as second_exc:
        logger.warning(
            f"[{log_tag}] retry 仍失败, 走 fallback. err={type(second_exc).__name__}: {str(second_exc)[:200]}"
        )
        return None, final_usage


# ===== R10.5.51 cleanup: 删 sync try_parse_with_retry (25 行) =====
# 旧版同步版, R10.5.47 早期同步版, 已被 async parse_with_retry_async 取代.
# 留过 fallback 但实际项目没用到 (生产都走 parse_with_retry_async).
# 旧 tests/test_agent_pydantic.py:198 等 4 处调用也迁到 async 路径 (见测试 commit).
# 历史 commit (R10.5.47): 引入; (R10.5.51): 标记 deprecated; (本清理): 删.
