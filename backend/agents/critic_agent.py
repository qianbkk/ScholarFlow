"""
Phase 3: Critic Agent - 独立评审节点
对论文进行红蓝对抗评审，识别方法论缺陷和证据强度
"""
import logging
from typing import Optional
from backend.models.state import SearchState
from backend.utils.llm_client import call_llm
from backend.agents._step_helper import _step  # R10.5.55

logger = logging.getLogger(__name__)


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
    critic_results = []

    logger.info(f"[critic_agent] 开始评审 {len(ranked_papers)} 篇论文")
    
    for i, paper in enumerate(ranked_papers[:10]):  # 限制最多评审前 10 篇
        try:
            title = paper.get("title", "无标题")
            abstract = paper.get("abstract", "无摘要")
            query = state.get("original_query", "")
            
            prompt = CRITIC_PROMPT_TEMPLATE.format(
                title=title,
                abstract=abstract,
                query=query
            )
            
            # R10.5.31 (F2): call_llm 返 (text, usage) tuple, 旧版直接当 str 用
            # → line 87 response_text.find('{') 抛 'tuple' has no attribute 'find'.
            # 解 tuple 拿 text, 用法保持一致.
            response_text, _usage = await call_llm(
                prompt=prompt,
                # D1 (P0-3): 旧版用 model="gpt-4o-mini" + temperature=0.3, 这 2 个
                # 都是 call_llm() 不接受的 kwarg (call_llm 只接 model_override, 无 temperature),
                # 导致 TypeError + 10 次重试. 改用 model_override= + task_type="fast"
                # (tier=fast → cfg['fast_model'], 跟"轻量模型批量评审"意图一致).
                model_override="gpt-4o-mini",
                task_type="fast",
                provider=provider,
                max_tokens=500,
                json_mode=True,  # critic 评审需要 JSON 结构化输出
            )

            # 解析 JSON 响应
            import json
            try:
                # 尝试提取 JSON (LLM 可能包裹在 markdown 中)
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    review = json.loads(json_str)
                else:
                    review = {"error": "无法解析 JSON 响应"}
            except json.JSONDecodeError:
                review = {"error": "JSON 解析失败", "raw_response": response_text[:200]}
            
            # 注入论文 ID
            review["paper_id"] = paper.get("paper_id")
            review["reviewed"] = True
            
            critic_results.append(review)
            
            logger.info(
                f"[critic_agent] 论文 {i+1}/{min(10, len(ranked_papers))}: "
                f"quality={review.get('quality_score', 'N/A')}, "
                f"recommendation={review.get('recommendation', 'N/A')}"
            )
            
        except Exception as e:
            logger.warning(f"[critic_agent] 评审论文 {i+1} 失败：{e}")
            critic_results.append({
                "paper_id": paper.get("paper_id"),
                "error": str(e),
                "reviewed": False
            })
    
    # 将评审结果注入 state
    updated_state = dict(state)
    updated_state["critic_reviews"] = critic_results
    
    # 更新成本追踪 (critic 节点的额外开销)
    # 注意：call_llm 内部已更新 total_cost_usd 和 total_tokens_used
    
    logger.info(f"[critic_agent] 完成评审，{len(critic_results)} 篇论文已评审")
    _step(state, "critic", f"✅ Critic review complete · {len(critic_results)} adopted")

    return updated_state
