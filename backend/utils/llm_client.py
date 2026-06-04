"""
ScholarFlow 多模型路由客户端
=============================

支持的 provider：
  - kimi    : Moonshot Kimi K2.5 (国内直连, Anthropic 协议)
  - glm     : 智谱 GLM-4.5 (国内直连, Anthropic 协议)
  - minimax : MiniMax-M3 (国内直连, Anthropic 协议)
  - anthropic: Claude 官方 (需 VPN)

当 LLM_MOCK=true 时，所有调用走离线 mock 响应（无网络也能跑通流水线）。
"""
import os
import json
import asyncio
import time
import re
from typing import Optional

import anthropic
from openai import AsyncOpenAI

from backend.config import (
    LLM_PROVIDER,
    LLM_MOCK,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    get_provider_config,
)


# ===== 路由策略 =====
TASK_MODEL_TIER = {
    "complex_reason":  "flagship",
    "fast_score":      "fast",
    "batch_filter":    "fast",
    "synthesis":       "flagship",
    "refine_strategy": "flagship",
}


# ===== 成本表（USD per 1M tokens，估算值）=====
MODEL_COST_PER_1M = {
    "claude-sonnet-4-6":              {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001":      {"input": 0.25,   "output": 1.25},
    "kimi-k2.5":                      {"input": 0.15,   "output": 2.0},
    "kimi-k2.6":                      {"input": 0.20,   "output": 2.5},
    "glm-4.5":                        {"input": 0.6,    "output": 2.2},
    "glm-4.5-air":                    {"input": 0.2,    "output": 0.8},
    "glm-4.6":                        {"input": 0.6,    "output": 2.2},
    "MiniMax-M3":                    {"input": 1.0,    "output": 3.0},
    "MiniMax-M2.7":                  {"input": 0.3,    "output": 1.0},
    "deepseek-chat":                  {"input": 0.27,   "output": 1.1},
    "deepseek-reasoner":              {"input": 0.55,   "output": 2.19},
    "mock":                            {"input": 0.0,    "output": 0.0},
}

DEFAULT_COST = {"input": 1.0, "output": 3.0}


def _calc_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = MODEL_COST_PER_1M.get(model, DEFAULT_COST)
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


# ===== 客户端单例 =====
_clients: dict[str, anthropic.AsyncAnthropic] = {}
_deepseek_client: Optional[AsyncOpenAI] = None


def _get_anthropic_client(provider: str) -> Optional[anthropic.AsyncAnthropic]:
    if provider in _clients:
        return _clients[provider]
    cfg = get_provider_config(provider)
    if not cfg.get("enabled"):
        return None
    try:
        client = anthropic.AsyncAnthropic(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            timeout=30.0,
            max_retries=1,
        )
        _clients[provider] = client
        return client
    except Exception as e:
        print(f"[llm_client] Failed to create client for {provider}: {e}")
        return None


def _get_deepseek_client() -> Optional[AsyncOpenAI]:
    global _deepseek_client
    if _deepseek_client is not None:
        return _deepseek_client
    if not DEEPSEEK_API_KEY:
        return None
    try:
        _deepseek_client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=30.0,
            max_retries=1,
        )
        return _deepseek_client
    except Exception as e:
        print(f"[llm_client] Failed to create DeepSeek client: {e}")
        return None


# ===== Mock 响应生成器 =====

def _mock_query_decompose(prompt: str) -> str:
    """Mock 查询分解：返回 4-5 个英文子查询。

    关键修复：从 prompt 提取实际查询（不是用整个 prompt 作为查询）。
    """
    # 从 prompt 提取真正的用户查询
    actual_query = prompt
    m = re.search(r"Original query:\s*(.+?)(?:\n|$)", prompt)
    if m:
        actual_query = m.group(1).strip()
    else:
        m2 = re.search(r"Query:\s*(.+?)(?:\n|$)", prompt)
        if m2:
            actual_query = m2.group(1).strip()
        else:
            # 短查询：截取到第一个换行
            actual_query = prompt.split("\n")[0].strip()

    base = actual_query.strip()
    base_en = base
    cn_to_en = {
        "大语言模型": "large language model",
        "代码生成": "code generation",
        "多智能体": "multi-agent",
        "强化学习": "reinforcement learning",
        "科研": "scientific research",
        "综述": "survey",
        "应用": "applications",
        "知识图谱": "knowledge graph",
        "嵌入": "embedding",
        "扩散": "diffusion",
        "语音识别": "speech recognition",
        "自监督": "self-supervised",
        "对比": "contrastive",
        "目标检测": "object detection",
        "联邦": "federated",
        "隐私": "privacy",
        "推荐系统": "recommender system",
        "协同过滤": "collaborative filtering",
        "图卷积": "graph convolution",
        "图注意力": "graph attention",
        "图嵌入": "graph embedding",
        "深度学习": "deep learning",
        "神经网络": "neural network",
    }
    for cn, en in cn_to_en.items():
        base_en = base_en.replace(cn, en)
    base_en = base_en.strip() or base

    return json.dumps({
        "analysis": f"原始查询「{base}」的研究意图分析：聚焦学术前沿，自动分解为多角度子查询。",
        "sub_queries": [
            f"{base_en} methods",
            f"{base_en} survey",
            f"{base_en} recent advances",
            f"{base_en} benchmark",
            f"{base_en} applications",
        ],
        "key_terms": base_en.split()[:3],
    }, ensure_ascii=False)


def _mock_relevance_score(paper_title: str, query: str) -> str:
    """Mock 相关性评分：基于关键词重合度 + 中英混合。"""
    import sys
    print(f"[MOCK_REL] pid={os.getpid()} query={query[:30]!r} title={paper_title[:30]!r}", file=sys.stderr, flush=True)
    q_lower = query.lower()
    t_lower = paper_title.lower()
    # 英文 word 匹配
    query_words = set(re.findall(r"[a-z]+", q_lower))
    title_words = set(re.findall(r"[a-z]+", t_lower))
    overlap = len(query_words & title_words)
    # 中文片段匹配（query 和 title 都包含中文字符时）
    cn_query = re.findall(r"[一-鿿]+", q_lower)
    cn_title = re.findall(r"[一-鿿]+", t_lower)
    cn_overlap = 0
    for q_seg in cn_query:
        for t_seg in cn_title:
            # 单字覆盖
            common = set(q_seg) & set(t_seg)
            if len(common) >= 1 and len(q_seg) >= 2:
                cn_overlap = max(cn_overlap, min(len(common), 2))

    total_overlap = overlap + cn_overlap
    if total_overlap >= 4:
        score = 9.0
    elif total_overlap >= 2:
        score = 7.5
    elif total_overlap >= 1:
        score = 6.0
    else:
        score = 2.0  # 无相关：低分，让权威性无法独占排序

    return json.dumps({
        "relevance": score,
        "reason": f"Overlap={total_overlap} (en={overlap}, cn={cn_overlap}).",
    }, ensure_ascii=False)


def _mock_refine(prompt: str, top5_titles: list[str]) -> str:
    """Mock 查询改写：从 prompt 提取真实 query，返回 3 个新子查询。"""
    actual_query = prompt
    m = re.search(r"Original query:\s*(.+?)(?:\n|$)", prompt)
    if m:
        actual_query = m.group(1).strip()
    else:
        m2 = re.search(r"Query:\s*(.+?)(?:\n|$)", prompt)
        if m2:
            actual_query = m2.group(1).strip()
        else:
            actual_query = prompt.split("\n")[0].strip()[:60]
    return json.dumps({
        "gap_analysis": f"基于 Top5 结果，补充「{actual_query}」的应用与对比研究维度。",
        "new_sub_queries": [
            f"{actual_query} evaluation",
            f"{actual_query} comparison",
            f"{actual_query} limitations",
        ],
    }, ensure_ascii=False)


def _mock_synthesis(prompt: str, ranked_count: int) -> str:
    """Mock 综述报告：返回结构化 Markdown。
    关键修复：从 prompt 中提取真实研究问题（不再使用 prompt 前 80 字符）。"""
    # 从 prompt 提取研究问题
    m = re.search(r"研究问题[：:]\s*(.+?)(?:\n|$)", prompt)
    if m:
        query = m.group(1).strip()
    else:
        m2 = re.search(r"Original query:\s*(.+?)(?:\n|$)", prompt)
        if m2:
            query = m2.group(1).strip()
        else:
            # 兜底：用 prompt 第一行
            query = prompt.split("\n")[0].strip()[:60]
    if not query:
        query = "（未指定查询）"

    return f"""## 研究概述
针对查询「{query}」，ScholarFlow 通过 8 节点流水线（查询分解 → 双源检索 → 引文扩展 → 三维排序 → 自适应改写 → 综述生成 → 图谱构建 → 成本汇总）从 Semantic Scholar 与 OpenAlex 汇总后返回 Top {ranked_count} 篇高质量论文。

## 核心论文推荐（Top 5）
1. **Attention Is All You Need** [2017] — 提出 Transformer 架构，开启大模型时代（cite 90000+）
2. **BERT: Pre-training of Deep Bidirectional Transformers** [2018] — 双向预训练语言模型（cite 50000+）
3. **GPT-3: Language Models are Few-Shot Learners** [2020] — Few-shot 学习的标志性工作（cite 30000+）
4. **Llama 2: Open Foundation and Fine-Tuned Chat Models** [2023] — 开源大语言模型代表
5. **A Survey of Large Language Models** [2023] — LLM 综述论文

## 研究方向分类

### 架构与方法 (Architecture)
- **Attention Is All You Need** — 自注意力机制奠基
- **BERT** — 双向预训练范式
- **GPT-3** — 规模化与 in-context learning

### 评测与基准 (Evaluation)
- **Llama 2** — 工业级模型评测实践
- **A Survey of LLMs** — 综合 benchmark 综述

## 关键研究趋势
1. **规模效应 (Scaling Laws)**：模型参数与数据规模呈幂律关系
2. **指令微调与 RLHF**：从预训练到对齐的范式转变
3. **多模态融合**：从纯文本走向图文音统一表征

## 延伸阅读
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) — Transformer 原论文
- [BERT](https://arxiv.org/abs/1810.04805) — 双向预训练语言模型
- [GPT-3](https://arxiv.org/abs/2005.14165) — Few-shot 学习的里程碑

## 检索说明
本次检索使用 ScholarFlow 8 节点流水线，数据源为 Semantic Scholar + OpenAlex，迭代轮次 = 配置 max_iterations，论文数 = {ranked_count}，评分方法为三维加权（相关性 50% + 权威性 30% + 一致性 20%）。

> 注：当前为 mock 模式（LLM_MOCK=true），报告由本地模板生成。生产环境请配置 LLM_PROVIDER=kimi|glm|minimax 并设置 LLM_MOCK=false 启用真实 LLM。
"""


def _mock_response(prompt: str, task_type: str, json_mode: bool) -> str:
    """根据 task_type 路由到对应 mock 函数。"""
    if task_type == "complex_reason":
        return _mock_query_decompose(prompt)
    if task_type == "fast_score":
        # 从 prompt 中提取 paper title 和 query
        m_title = re.search(r"Paper:\s*(.+)", prompt)
        m_query = re.search(r"Query:\s*(.+)", prompt)
        if m_title and m_query:
            return _mock_relevance_score(m_title.group(1).strip(), m_query.group(1).strip())
        return json.dumps({"relevance": 6.0, "reason": "mock fallback"})
    if task_type == "refine_strategy":
        return _mock_refine(prompt, [])
    if task_type == "synthesis":
        return _mock_synthesis(prompt, 10)
    # 兜底
    return json.dumps({"result": "mock"})


# ===== 公开 API =====

async def call_llm(
    prompt: str,
    task_type: str = "complex_reason",
    system: str = "You are a helpful academic research assistant.",
    max_tokens: int = 2000,
    json_mode: bool = False,
    provider: Optional[str] = None,
    model_override: Optional[str] = None,
) -> tuple[str, dict]:
    """
    统一 LLM 调用入口。
    Returns: (response_text, usage_info)
    """
    # ===== Mock 模式 =====
    if LLM_MOCK:
        return await _call_mock(prompt, task_type, json_mode)

    provider = (provider or LLM_PROVIDER).lower()
    cfg = get_provider_config(provider)

    if model_override:
        model = model_override
    else:
        tier = TASK_MODEL_TIER.get(task_type, "flagship")
        model = cfg.get("fast_model" if tier == "fast" else "model", cfg.get("model", ""))

    if provider == "deepseek" or model.startswith("deepseek-"):
        return await _call_deepseek(prompt, system, max_tokens, json_mode)
    return await _call_anthropic_compatible(
        provider, model, prompt, system, max_tokens, json_mode
    )


async def _call_mock(prompt: str, task_type: str, json_mode: bool) -> tuple[str, dict]:
    """Mock 调用：返回预置响应。"""
    # 模拟 50ms 延迟
    await asyncio.sleep(0.05)
    text = _mock_response(prompt, task_type, json_mode)
    # 估算 token
    input_tokens = max(1, len(prompt) // 4)
    output_tokens = max(1, len(text) // 4)
    usage = {
        "model": "mock",
        "provider": "mock",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": 0.0,
    }
    return text, usage


async def _call_anthropic_compatible(
    provider: str, model: str, prompt: str, system: str, max_tokens: int, json_mode: bool
) -> tuple[str, dict]:
    client = _get_anthropic_client(provider)
    if client is None:
        return "", {
            "model": model, "provider": provider,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "error": f"provider {provider} not configured",
        }
    if json_mode:
        system = system + "\n\nIMPORTANT: Respond with valid JSON only. No prose, no markdown code blocks."

    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        if resp.content:
            for block in resp.content:
                if hasattr(block, "text"):
                    text += block.text
        usage = {
            "model": model,
            "provider": provider,
            "input_tokens": resp.usage.input_tokens if resp.usage else 0,
            "output_tokens": resp.usage.output_tokens if resp.usage else 0,
            "cost_usd": _calc_cost_usd(
                model,
                resp.usage.input_tokens if resp.usage else 0,
                resp.usage.output_tokens if resp.usage else 0,
            ),
        }
        return text, usage
    except Exception as e:
        print(f"[llm_client] {provider}/{model} ERROR: {type(e).__name__}: {e}")
        return "", {
            "model": model, "provider": provider,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "error": str(e)[:200],
        }


async def _call_deepseek(
    prompt: str, system: str, max_tokens: int, json_mode: bool
) -> tuple[str, dict]:
    client = _get_deepseek_client()
    if client is None:
        return "", {
            "model": "deepseek-chat", "provider": "deepseek",
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "error": "DeepSeek API key not configured",
        }
    model = "deepseek-chat"
    try:
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        usage = {
            "model": model, "provider": "deepseek",
            "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
            "cost_usd": _calc_cost_usd(
                model,
                resp.usage.prompt_tokens if resp.usage else 0,
                resp.usage.completion_tokens if resp.usage else 0,
            ),
        }
        return text, usage
    except Exception as e:
        print(f"[llm_client] deepseek ERROR: {type(e).__name__}: {e}")
        return "", {
            "model": model, "provider": "deepseek",
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "error": str(e)[:200],
        }


def merge_usage_into_state(state: dict, usage: dict) -> dict:
    if not usage:
        usage = {"model": "unknown", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    model = usage.get("model", "unknown")
    existing = dict(state.get("model_usage", {}))

    if model not in existing:
        existing[model] = {"tokens": 0, "cost": 0.0}
    existing[model]["tokens"] += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    existing[model]["cost"] += usage.get("cost_usd", 0.0)

    return {
        "total_tokens_used": state.get("total_tokens_used", 0)
        + usage.get("input_tokens", 0)
        + usage.get("output_tokens", 0),
        "total_cost_usd": state.get("total_cost_usd", 0.0) + usage.get("cost_usd", 0.0),
        "model_usage": existing,
    }


async def _self_test():
    prompt = "Reply with the single word: OK"
    text, usage = await call_llm(prompt, task_type="fast_score", max_tokens=20)
    print(f"[self_test] provider={usage.get('provider')}, model={usage.get('model')}, "
          f"tokens_in={usage.get('input_tokens')}, tokens_out={usage.get('output_tokens')}, "
          f"cost=${usage.get('cost_usd', 0):.6f}, err={usage.get('error')}")
    return text, usage


if __name__ == "__main__":
    asyncio.run(_self_test())
