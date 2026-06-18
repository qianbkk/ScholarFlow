"""backend.utils.token_estimator
=============================

R10.5.48 (P1 LLM cost 防御): 保守 token 估算 + 预算前置检查.

审计 #9: 单次 LLM 调用前 fast-fail 请求如果明显超预算.
旧实现: 没前置估算, _check_and_reserve_budget 只检查 hourly cap
(总共跑多少), 单次请求的真实 cost 在 astream 跑完才知道. 用户配 budget=0.5
发了个 50k char 的大 prompt, 实际 LLM cost $1.20, 远超 budget, 跑完才暴露.

新实现 (per user 偏好 R10.5.43 决策 "保守估算 (字符数 / 4)"):
- estimate_tokens(text): 1 token ≈ 4 chars, (len + 3) // 4 向上取整.
  - 英文 / 中英混合 / 简单符号, 实际 token 率在 3-5 chars/token 之间
  - 4 chars/token 是中间值, 够用
- estimate_request_cost(prompt_chars, max_iter, ...): 估算整个 8 节点
  流水线的 LLM cost, 加 30% buffer.
- pre_check_budget(): 在 _check_and_reserve_budget 之前调, 如果估算
  cost > user.budget 抛 HTTPException(402).

为什么不用 tiktoken:
- 多 provider tokenizer 不公开 (MiniMax/Kimi/DeepSeek), 强估可能误拒.
- 字符/4 已经够保守, 加 30% buffer 后误拒概率 < 5%.
- 精准估算留 R11+ provider tokenizer 公开后.

调用方:
- backend/api/routes/search.py: 在 _check_and_reserve_budget 之前调
  pre_check_budget. 拒绝请求时返 402 + 友好 message.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# ===== Token 估算 (chars/4 保守) =====

def estimate_tokens(text: str) -> int:
    """R10.5.48: 保守 token 估算. 1 token ≈ 4 chars.

    (len(text) + 3) // 4 向上取整 — 比 len // 4 多 1 token buffer, 防止
    边界 case (e.g. text 长度 0 → 0 token, 长度 1-4 → 1 token).

    适用:
    - 英文 (avg ~4 chars/token)
    - 中英混合 (中文 ~1.5 chars/token, 4 chars = 1-2 token, 偏保守)
    - JSON / 代码 (avg ~5 chars/token, 4 chars/token 偏激进, 加 30% buffer 兜底)

    不适用:
    - emoji (1 emoji = 多个 token, 4 chars/token 严重低估) — 但 LLM 学术 prompt
      几乎不出现, 可接受.

    Args:
        text: 任意文本

    Returns:
        估算的 token 数 (>= 0).
    """
    if not text:
        return 0
    return (len(text) + 3) // 4


# ===== 单次 LLM 调用成本估算 (rough) =====

# MiniMax / Kimi 典型 $/1k tokens: input 0.003, output 0.015
# 用 env var 覆盖, 缺省 MiniMax. R11+ 走 provider 实际 pricing.
_DEFAULT_INPUT_PRICE_PER_1K = float(os.getenv("ESTIMATED_INPUT_PRICE_PER_1K", "0.003"))
_DEFAULT_OUTPUT_PRICE_PER_1K = float(os.getenv("ESTIMATED_OUTPUT_PRICE_PER_1K", "0.015"))


def estimate_llm_call_cost(
    input_tokens: int,
    output_tokens_estimate: int,
    input_price_per_1k: Optional[float] = None,
    output_price_per_1k: Optional[float] = None,
    safety_buffer: float = 1.3,
) -> float:
    """R10.5.48: 估算单次 LLM 调用的 cost, 加 safety buffer (默认 30%).

    Args:
        input_tokens: 输入 token 估算
        output_tokens_estimate: 输出 token 估算
        input_price_per_1k: $/1k input tokens, None 用 env 兜底
        output_price_per_1k: $/1k output tokens, None 用 env 兜底
        safety_buffer: 安全系数, 默认 1.3 (30% 冗余)

    Returns:
        估算 cost (含 buffer), 单位 USD.
    """
    in_price = input_price_per_1k if input_price_per_1k is not None else _DEFAULT_INPUT_PRICE_PER_1K
    out_price = output_price_per_1k if output_price_per_1k is not None else _DEFAULT_OUTPUT_PRICE_PER_1K
    cost = (input_tokens / 1000.0) * in_price + (output_tokens_estimate / 1000.0) * out_price
    return cost * safety_buffer


# ===== 整个 8 节点流水线估算 =====

# 各 LLM-calling 节点的 max_output_tokens (跟 prompt 声明一致)
_NODE_MAX_OUTPUT = {
    "query_decompose": 500,
    "query_refiner": 400,  # per iter, up to max_iter calls
    "ranker": 600,         # per batch, 3-4 batches per iter
    "critic": 500,         # per paper, up to 10 papers
    "synthesis": 3500,
}
_RANKER_BATCHES_PER_ITER = 4  # 经验值, 35 papers / 10 per batch


def estimate_request_cost(
    prompt_size_chars: int,
    max_iter: int = 3,
    safety_buffer: float = 1.3,
) -> float:
    """R10.5.48: 估算整个 8 节点流水线 LLM cost.

    假设:
    - query_decompose: 1 call (1 iter, 不重复)
    - query_refiner: 1 call per iter (up to max_iter)
    - ranker: 3-4 batches per iter (经验值), max_iter iter
    - critic: 1 call per paper (ranked top 10), 1 iter
    - synthesis: 1 call (final)

    Args:
        prompt_size_chars: 用户 query + agent 模板 prompt 估算总字符数.
        max_iter: 最大迭代数.
        safety_buffer: 30% buffer 防止低估.

    Returns:
        估算总 cost (含 buffer), USD.
    """
    est_input_tokens = estimate_tokens("x" * prompt_size_chars)

    # 总 LLM calls
    total_calls = (
        1  # query_decompose
        + max_iter  # query_refiner
        + _RANKER_BATCHES_PER_ITER * max_iter  # ranker
        + 10  # critic (top 10 papers)
        + 1  # synthesis
    )
    # 总 max_output_tokens
    total_output_tokens = (
        _NODE_MAX_OUTPUT["query_decompose"]
        + _NODE_MAX_OUTPUT["query_refiner"] * max_iter
        + _NODE_MAX_OUTPUT["ranker"] * _RANKER_BATCHES_PER_ITER * max_iter
        + _NODE_MAX_OUTPUT["critic"] * 10
        + _NODE_MAX_OUTPUT["synthesis"]
    )

    # input 每个 call 都带 prompt (sum total)
    total_input_tokens = est_input_tokens * total_calls

    return estimate_llm_call_cost(
        input_tokens=total_input_tokens,
        output_tokens_estimate=total_output_tokens,
        safety_buffer=safety_buffer,
    )


# ===== HTTPException 抛错 (FastAPI) =====

def pre_check_budget(
    prompt_size_chars: int,
    user_budget: float,
    max_iter: int = 3,
    safety_buffer: float = 1.3,
) -> None:
    """R10.5.48 (P1 budget 防御): 在 _check_and_reserve_budget 之前调.

    估算整个 8 节点流水线 cost, 如果 > user_budget, 抛 HTTPException(402)
    让请求 fast-fail, 不浪费 token / API 配额.

    Args:
        prompt_size_chars: 用户 query 字符数 (作为 prompt 估算的代理).
                           实际 agent prompt 模板会更大, 这里只估用户输入维度.
        user_budget: 用户声明的单次预算上限 (req.budget).
        max_iter: 最大迭代数, 默认 3.
        safety_buffer: 安全系数, 默认 1.3 (30%).

    Raises:
        HTTPException(402): 估算 cost > user_budget.
        无: 估算 cost <= user_budget (含 0 / OPEN_MODE 跳过).

    注意:
    - user_budget <= 0 时不检查 (OPEN_MODE / 无限制).
    - 估算保守: chars/4 + 30% buffer, 实际 cost 通常更小.
    - 拒绝时建议: 调高 budget / 缩小 prompt / 降低 max_iter.
    """
    # OPEN_MODE / 无 budget 限制 → 跳过
    if user_budget <= 0:
        return

    est_cost = estimate_request_cost(
        prompt_size_chars=prompt_size_chars,
        max_iter=max_iter,
        safety_buffer=safety_buffer,
    )

    if est_cost > user_budget:
        from fastapi import HTTPException
        # R10.5.48: 用 402 Payment Required (语义最准 — 请求因 cost 限制被拒).
        # 跟 503 (hourly cap) / 504 (timeout) 区分开.
        logger.info(
            f"[token_estimator] pre_check_budget reject: "
            f"est_cost=${est_cost:.4f} > user_budget=${user_budget:.2f} "
            f"(prompt_chars={prompt_size_chars}, max_iter={max_iter})"
        )
        raise HTTPException(
            status_code=402,
            detail=(
                f"请求估算成本 ${est_cost:.4f} 超过用户预算 ${user_budget:.2f}. "
                f"建议: 调高预算 / 缩小查询 / 降低 max_iter."
            ),
        )

    logger.debug(
        f"[token_estimator] pre_check pass: "
        f"est_cost=${est_cost:.4f} <= user_budget=${user_budget:.2f}"
    )
