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

from pydantic import BaseModel, Field, RootModel, field_validator


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


# ===== 通用 Pydantic 解析器 =====

def try_parse_with_retry(
    raw_text: str,
    schema_cls: type[BaseModel],
    retry_prompt_prefix: str = "",
    llm_call_fn=None,
    state: Optional[dict] = None,
) -> tuple[Optional[BaseModel], Optional[object]]:
    """R10.5.47: Pydantic v2 解析 LLM 输出, 失败时 1 次重试.

    流程:
    1. Pydantic v2 model_validate_json 尝试解析 raw_text
    2. 失败 → 1 次 LLM 重试 (prompt 加 retry_prompt_prefix 提示格式)
    3. 仍失败 → 返回 (None, last_exception) 让调用方走 fallback

    Args:
        raw_text: LLM 返回的原始文本 (可能含 markdown ```json 围栏)
        schema_cls: Pydantic v2 BaseModel 子类
        retry_prompt_prefix: 重试时附加到 prompt 的格式提示
        llm_call_fn: 重试时调的 LLM 函数, 签名 (prompt, ...) → (text, usage)
                      None = 不重试, 直接 fallback
        state: 透传给 llm_call_fn 的状态 (e.g. provider)

    Returns:
        (parsed_model, None) 成功
        (None, exception) 失败 (1 次重试后仍坏)
    """
    # 第一次解析 — 剥 markdown 围栏
    cleaned = _strip_markdown_fence(raw_text)
    try:
        return schema_cls.model_validate_json(cleaned), None
    except Exception as first_exc:
        if llm_call_fn is None:
            return None, first_exc
        # 第二次重试 — 加格式提示
        if retry_prompt_prefix:
            try:
                retry_text, _ = llm_call_fn(retry_prompt_prefix)
                retry_cleaned = _strip_markdown_fence(retry_text)
                return schema_cls.model_validate_json(retry_cleaned), None
            except Exception as second_exc:
                return None, second_exc
        return None, first_exc


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
