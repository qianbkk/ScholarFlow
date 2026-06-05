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
from backend.utils.scrub import scrub_sensitive  # VULN-004


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
        print(f"[llm_client] Failed to create client for {provider}: {scrub_sensitive(str(e))}")
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
        print(f"[llm_client] Failed to create DeepSeek client: {scrub_sensitive(str(e))}")
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


def _mock_consistency_score(paper_title: str, query: str) -> str:
    """Mock 一致性评分：基于论文与 query 的领域匹配度。
    关键修复（B-005）：ranker_agent 一致性 prompt 使用 "Query domain:" 字面量，
    与原 _mock_response 路由正则 "Query:\\s*" 不匹配，导致 mock 永远走兜底。
    本函数专用于 consistency 维度。
    """
    q_lower = query.lower()
    t_lower = paper_title.lower()
    query_words = set(re.findall(r"[a-z]+", q_lower))
    title_words = set(re.findall(r"[a-z]+", t_lower))
    overlap = len(query_words & title_words)

    # 中文匹配
    cn_query = re.findall(r"[一-鿿]+", q_lower)
    cn_title = re.findall(r"[一-鿿]+", t_lower)
    cn_overlap = 0
    for q_seg in cn_query:
        for t_seg in cn_title:
            common = set(q_seg) & set(t_seg)
            if len(common) >= 1 and len(q_seg) >= 2:
                cn_overlap = max(cn_overlap, min(len(common), 2))

    total = overlap + cn_overlap
    # 一致性 7.0 基础分（学术论文通常内部一致性不错）
    # 与 query 严重不匹配的论文压低，模拟 "领域外论文"
    if total >= 2:
        score = 8.0
    elif total >= 1:
        score = 7.0
    else:
        score = 4.5  # 关键词完全无交集 → 一致性低
    return json.dumps({
        "consistency": score,
        "reason": f"Mock consistency (overlap={total}).",
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
    关键修复：从 prompt 中提取真实研究问题（不再使用 prompt 前 80 字符）。
    关键修复（B-002 / 任务 3）：Top5/分类/趋势/延伸阅读全部动态从 prompt 中的
    **[Paper i]** {title}\nYear: {year} | Citations: {citation_count} | Venue: {venue}
    Relevance: {relevance_score} | URL: {url}\nAbstract: {abstract[:400]}
    块解析，不再硬编码 Transformer/BERT/GPT-3/Llama 2。
    """
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

    # ===== 关键修复：从 prompt 解析真实论文块（按 [Paper i] 块切分） =====
    paper_pattern = re.compile(
        r"\*\*\[Paper (\d+)\]\*\*\s+(.+?)\n"
        r"Year:\s*(\d+).*?Citations:\s*(\d+).*?Venue:\s*(.*?)\n"
        r"Relevance:\s*([\d.]+).*?URL:\s*(\S+).*?\n"
        r"Abstract:\s*(.+?)(?=\n\*\*\[Paper|\Z)",
        re.DOTALL,
    )
    papers: list[dict] = []
    for m in paper_pattern.finditer(prompt):
        papers.append({
            "idx": int(m.group(1)),
            "title": m.group(2).strip(),
            "year": m.group(3).strip(),
            "citations": int(m.group(4) or 0),
            "venue": (m.group(5) or "").strip(),
            "relevance": float(m.group(6) or 0.0),
            "url": (m.group(7) or "").strip(),
            "abstract": (m.group(8) or "").strip()[:200],
        })
    # 按 idx 排序（保证稳定顺序）
    papers.sort(key=lambda p: p["idx"])

    if not papers:
        # 兜底：解析失败时返回极简报告
        return f"""## 研究概述
针对查询「{query}」，ScholarFlow 从 Semantic Scholar + OpenAlex 汇总后返回 {ranked_count} 篇论文。

## 检索说明
本次检索使用 ScholarFlow 8 节点流水线。注：当前为 mock 模式，且 prompt 中未识别到论文块，无法生成结构化 Top 列表。
"""

    # ===== 动态 Top 5 =====
    top5 = papers[:5]
    top5_lines = []
    for i, p in enumerate(top5, 1):
        year = p["year"] or "?"
        cites = p["citations"]
        cite_str = f"cite {cites}+" if cites >= 1000 else f"cite {cites}"
        top5_lines.append(
            f"{i}. **{p['title']}** [{year}] — 相关性 {p['relevance']:.1f}/10（{cite_str}）"
        )
    top5_block = "\n".join(top5_lines)

    # ===== 研究方向分类：按 venue 聚类 =====
    # 聚类 venue 相同的论文；无 venue 时退化为按 title 关键词聚类
    venue_groups: dict[str, list[dict]] = {}
    no_venue_papers: list[dict] = []
    for p in papers:
        v = (p.get("venue") or "").strip()
        if v:
            venue_groups.setdefault(v, []).append(p)
        else:
            no_venue_papers.append(p)

    cluster_blocks: list[str] = []
    if venue_groups:
        for venue, group in list(venue_groups.items())[:3]:
            cluster_blocks.append(f"### {venue}（{len(group)} 篇）")
            for p in group[:3]:
                cluster_blocks.append(f"- **{p['title']}** [{p['year']}] — 相关性 {p['relevance']:.1f}/10")
    if no_venue_papers:
        cluster_blocks.append("### 其他研究")
        for p in no_venue_papers[:3]:
            cluster_blocks.append(f"- **{p['title']}** [{p['year']}] — 相关性 {p['relevance']:.1f}/10")
    if not cluster_blocks:
        cluster_blocks = ["- （无可分类的 venue 信息）"]
    cluster_block = "\n".join(cluster_blocks)

    # ===== 关键研究趋势：按时间排序，最早 2 篇 + 最近 2 篇 =====
    by_year = sorted(papers, key=lambda p: int(p["year"]) if p["year"].isdigit() else 0)
    earliest2 = [p for p in by_year if p["year"].isdigit()][:2]
    latest2 = [p for p in by_year if p["year"].isdigit()][-2:] if len(by_year) >= 2 else []
    trend_lines = []
    for i, p in enumerate(earliest2, 1):
        trend_lines.append(
            f"{i}. **{p['title'][:80]}** [{p['year']}] 为该方向奠基性工作，相关性 {p['relevance']:.1f}/10。"
        )
    for i, p in enumerate(latest2, len(earliest2) + 1):
        trend_lines.append(
            f"{i}. **前沿工作**：**{p['title'][:80]}** [{p['year']}] 反映当前研究热点，相关性 {p['relevance']:.1f}/10。"
        )
    if not trend_lines:
        trend_lines = ["1. （论文年份信息不足，无法生成趋势分析）"]
    trend_block = "\n".join(trend_lines)

    # ===== 延伸阅读：取 Top 5 论文的 URL =====
    extend_lines = []
    for p in papers[:5]:
        url = p["url"] or ""
        title_short = p["title"][:60]
        extend_lines.append(f"- [{title_short}]({url}) — 相关性 {p['relevance']:.1f}/10")
    extend_block = "\n".join(extend_lines)

    return f"""## 研究概述
针对查询「{query}」，ScholarFlow 通过 8 节点流水线（查询分解 → 双源检索 → 引文扩展 → 三维排序 → 自适应改写 → 综述生成 → 图谱构建 → 成本汇总）从 Semantic Scholar 与 OpenAlex 汇总后返回 Top {ranked_count} 篇高质量论文。

## 核心论文推荐（Top 5）
{top5_block}

## 研究方向分类
{cluster_block}

## 关键研究趋势
{trend_block}

## 延伸阅读
{extend_block}

## 检索说明
本次检索使用 ScholarFlow 8 节点流水线，数据源为 Semantic Scholar + OpenAlex，论文数 = {ranked_count}，评分方法为三维加权（相关性 50% + 权威性 30% + 一致性 20%）。

> 注：当前为 mock 模式（LLM_MOCK=true），报告由本地模板基于真实 ranked_papers 动态生成。生产环境请配置 LLM_PROVIDER=kimi|glm|minimax 并设置 LLM_MOCK=false 启用真实 LLM。
"""


def _mock_batch_score(prompt: str, is_consistency: bool) -> str:
    """Mock 批量评分：解析 prompt 中的 [i+1] Title 块，按 query-title 重叠度打分。

    返回 JSON 格式：
      {
        "scores": {"1": 7.5, "2": 8.0, ...},   # ranker_agent 实际读取
        "reasons": {"1": "...", "2": "..."}    # 可选说明
      }
    """
    # 1) 解析 query
    query = ""
    m = re.search(r"<user_query>([\s\S]*?)</user_query>", prompt)
    if m:
        query = m.group(1).strip()
        # 反转义 wrap_user_input 的 HTML 实体
        query = query.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    if not query:
        m2 = re.search(r"Query:\s*(.+?)(?:\n|$)", prompt)
        if m2:
            query = m2.group(1).strip()
    if not query:
        query = prompt.split("\n")[0].strip()[:60]
    if not query:
        query = ""

    # 2) 解析所有 [i+1] Title: 块
    title_pattern = re.compile(r"\[(\d+)\]\s+Title:\s*(.+?)(?:\nAbstract:|$)", re.DOTALL)
    paper_blocks = title_pattern.findall(prompt)
    if not paper_blocks:
        # 兜底：更宽松的 [i+1] Title: 匹配
        title_pattern2 = re.compile(r"\[(\d+)\]\s+Title:\s*(.+)")
        paper_blocks = title_pattern2.findall(prompt)

    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
    q_lower = query.lower()
    query_words = set(re.findall(r"[a-z]+", q_lower))
    cn_query = re.findall(r"[一-鿿]+", q_lower)

    for idx_str, title in paper_blocks:
        title = (title or "").strip()[:200]
        t_lower = title.lower()
        title_words = set(re.findall(r"[a-z]+", t_lower))
        overlap = len(query_words & title_words)
        cn_title = re.findall(r"[一-鿿]+", t_lower)
        cn_overlap = 0
        for q_seg in cn_query:
            for t_seg in cn_title:
                common = set(q_seg) & set(t_seg)
                if len(common) >= 1 and len(q_seg) >= 2:
                    cn_overlap = max(cn_overlap, min(len(common), 2))
        total_overlap = overlap + cn_overlap

        if is_consistency:
            # 一致性维度：基础分较高
            if total_overlap >= 2:
                score = 8.0
            elif total_overlap >= 1:
                score = 7.0
            else:
                score = 5.5
        else:
            # 相关性维度
            if total_overlap >= 4:
                score = 9.0
            elif total_overlap >= 2:
                score = 8.0
            elif total_overlap >= 1:
                score = 7.5
            else:
                score = 5.0
        scores[idx_str] = round(score, 1)
        reasons[idx_str] = f"Batch overlap={total_overlap} (en={overlap}, cn={cn_overlap})."

    return json.dumps({
        "scores": scores,
        "reasons": reasons,
    }, ensure_ascii=False)


def _mock_response(prompt: str, task_type: str, json_mode: bool) -> str:
    """根据 task_type 路由到对应 mock 函数。

    B-005 修复：consistency prompt 使用 "Query domain:" 而 relevance 用 "Query:"。
    通过 prompt 特征区分两者，避免 mock 永远走兜底。
    任务 2 修复：批量评分 prompt 使用 [i+1] Title + <paper_list>，新增 _mock_batch_score 处理。
    """
    if task_type == "complex_reason":
        return _mock_query_decompose(prompt)
    if task_type == "fast_score":
        # 批量评分（[i+1] Title: + <paper_list> 标签）— 优先匹配
        if re.search(r"\[\d+\]\s+Title:", prompt) or "<paper_list>" in prompt:
            is_cons = "consistency" in prompt.lower()
            return _mock_batch_score(prompt, is_consistency=is_cons)
        # 一致性评分 prompt 含 "consistency" 关键词 + "Query domain:" 字段
        if "consistency" in prompt.lower():
            m_title = re.search(r"Paper:\s*(.+)", prompt)
            m_query = re.search(r"Query domain:\s*(.+)", prompt)
            if m_title and m_query:
                return _mock_consistency_score(
                    m_title.group(1).strip(), m_query.group(1).strip()
                )
            return json.dumps({"consistency": 6.0, "reason": "mock consistency fallback"})
        # 相关性评分（默认 fast_score 走 relevance）
        m_title = re.search(r"Paper:\s*(.+)", prompt)
        m_query = re.search(r"Query:\s*(.+)", prompt)
        if m_title and m_query:
            return _mock_relevance_score(
                m_title.group(1).strip(), m_query.group(1).strip()
            )
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
        result = await _call_deepseek(prompt, system, max_tokens, json_mode)
    else:
        result = await _call_anthropic_compatible(
            provider, model, prompt, system, max_tokens, json_mode
        )
    # ===== 失败降级：real 失败时回退 mock，保证 8 节点流水线不卡住 =====
    text, usage = result
    if not text and usage.get("error"):
        print(f"[llm_client] {provider}/{model} failed: {scrub_sensitive(usage['error'])}  → fallback to mock")
        return await _call_mock(prompt, task_type, json_mode)
    return result


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
        print(f"[llm_client] {provider}/{model} ERROR: {type(e).__name__}: {scrub_sensitive(str(e))}")
        return "", {
            "model": model, "provider": provider,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "error": scrub_sensitive(str(e)),
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
        print(f"[llm_client] deepseek ERROR: {type(e).__name__}: {scrub_sensitive(str(e))}")
        return "", {
            "model": model, "provider": "deepseek",
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "error": scrub_sensitive(str(e)),
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
