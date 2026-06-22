"""
Phase 3: Critic Agent - 独立评审节点
对论文进行红蓝对抗评审，识别方法论缺陷和证据强度
"""
import asyncio
import json
import logging
from typing import Optional
from backend.models.state import SearchState
from backend.utils.llm_client import call_llm
from backend.agents._step_helper import _step  # R10.5.55

logger = logging.getLogger(__name__)

# P10 (P1-1 性能): critic LLM 评审并发上限. 旧实现 10 篇串行, 实际 20-50s.
# Semaphore(3) 允许 3 篇同时评, 10 篇分 4 波, 实测 6-15s. 跟 SS/OA 限流同档.
_CRITIC_SEMAPHORE_LIMIT = 3


CRITIC_PROMPT_TEMPLATE = """
你是一位严格的学术审稿人 (Critic Agent)。你的任务是对以下论文进行独立评审，
识别潜在的方法论缺陷、证据强度问题，并给出是否应该被综述采纳的建议。

## 待评审论文
标题：{title}
摘要：{abstract}

## 当前研究问题
{query}

## 评审要求
请以 JSON 格式输出评审结果，包含以下字段：
- quality_score: 0-10 的整数分数
- strengths: 优点列表 (最多 3 条)
- weaknesses: 缺陷/风险列表 (最多 3 条)
- methodology_issues: 方法论问题 (如样本量不足、未控制变量等)
- recommendation: "adopt" | "cautious" | "reject"
- confidence: 0.0-1.0 的置信度
- reasoning: 简要说明评审理由 (200 字以内)

## 注意事项
- 必须基于论文实际内容，不得臆造
- 如果摘要信息不足以判断，confidence 应降低
- 对于与当前研究问题高度相关但方法有缺陷的论文，recommendation 应为 "cautious"
- 输出必须是纯 JSON，不要 Markdown 格式
"""


async def critic_review_node(state: SearchState) -> SearchState:
    """
    Phase 3: Critic Agent 评审节点
    
    对 ranked_papers 中的每篇论文进行独立评审，
    将评审结果注入 state，供 synthesis 节点参考
    """
    ranked_papers = state.get("ranked_papers", [])
    if not ranked_papers:
        return state
    _step(state, "critic", f"🎯 启动 critic review · {len(ranked_papers)} papers")

    provider = state.get("provider")
    query = state.get("original_query", "")
    max_review = 10  # 限制最多评审前 10 篇
    papers_to_review = ranked_papers[:max_review]

    # P10 (P1-1 性能): 旧实现 10 篇串行 LLM, 实际 20-50s.
    # 新实现: asyncio.gather + Semaphore(_CRITIC_SEMAPHORE_LIMIT=3) 并发.
    # 10 篇分 4 波, 实测 6-15s, 节省 14-35s.
    # 注意: 顺序仍按 papers 索引, 但并发执行; 失败用 return_exceptions=True 兜底.
    logger.info(f"[critic_agent] 开始评审 {len(papers_to_review)} 篇论文 (并发 {_CRITIC_SEMAPHORE_LIMIT})")
    semaphore = asyncio.Semaphore(_CRITIC_SEMAPHORE_LIMIT)

    async def _review_one(i: int, paper: dict) -> dict:
        """并发评审单篇论文, 走 Semaphore 限流."""
        async with semaphore:
            try:
                title = paper.get("title", "无标题")
                abstract = paper.get("abstract", "无摘要")
                prompt = CRITIC_PROMPT_TEMPLATE.format(
                    title=title,
                    abstract=abstract,
                    query=query,
                )
                response_text, _usage = await call_llm(
                    prompt=prompt,
                    model_override="gpt-4o-mini",
                    task_type="fast",
                    provider=provider,
                    max_tokens=500,
                    json_mode=True,
                )
                # 解析 JSON 响应
                try:
                    json_start = response_text.find('{')
                    json_end = response_text.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        review = json.loads(response_text[json_start:json_end])
                    else:
                        review = {"error": "无法解析 JSON 响应"}
                except json.JSONDecodeError:
                    review = {"error": "JSON 解析失败", "raw_response": response_text[:200]}
                review["paper_id"] = paper.get("paper_id")
                review["reviewed"] = True
                logger.info(
                    f"[critic_agent] 论文 {i+1}/{len(papers_to_review)}: "
                    f"quality={review.get('quality_score', 'N/A')}, "
                    f"recommendation={review.get('recommendation', 'N/A')}"
                )
                return review
            except Exception as e:
                logger.warning(f"[critic_agent] 评审论文 {i+1} 失败: {e}")
                return {
                    "paper_id": paper.get("paper_id"),
                    "error": str(e),
                    "reviewed": False,
                }

    # gather + return_exceptions=True 兜底单个失败
    critic_results = await asyncio.gather(
        *[_review_one(i, p) for i, p in enumerate(papers_to_review)],
        return_exceptions=True,
    )
    # gather 异常 (系统级) 兜底成空 dict, 不让 critic 节点整体崩
    critic_results = [
        r if isinstance(r, dict) else {"error": str(r), "reviewed": False}
        for r in critic_results
    ]
    
    # 将评审结果注入 state
    updated_state = dict(state)
    updated_state["critic_reviews"] = critic_results
    
    # 更新成本追踪 (critic 节点的额外开销)
    # 注意：call_llm 内部已更新 total_cost_usd 和 total_tokens_used
    
    logger.info(f"[critic_agent] 完成评审，{len(critic_results)} 篇论文已评审")
    _step(state, "critic", f"✅ Critic review complete · {len(critic_results)} adopted")

    return updated_state
