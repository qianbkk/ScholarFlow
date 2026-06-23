"""
R10.5.93 — Stance / Study Type / Key Quote 分类器

借鉴自 4 家同类工具 (用户调研结论):
- Scite.ai: "Supporting / Contrasting / Mentioning" 引用立场分类
- Consensus.app: "Yes / No / Mixed" 立场 + 论文类型过滤
- Elicit: "Key Quote" 提取 + 论文类型 (RCT / meta-analysis) 标注

合并成一个 agent + 一次 LLM 调用:
1. stance: 每篇论文对研究问题的立场 (Supporting / Contrasting / Neutral / Mixed)
2. study_type: 论文类型 (RCT / meta-analysis / review / survey / method / case-study / other)
3. key_quote: 1 句关键引用 (从 abstract 抽取, ≤ 200 字)
4. consensus_summary: 跨所有论文的立场聚合 + 文字总结 (供前端 ConsensusMeter 显示)

参考实现: 复用 ranker_agent 的"批量 LLM 调用"模式 (一次调 LLM, JSON dict 输出),
节省 1 round-trip. 限制最多 10 篇 (跟 synthesis 同步).

R10.5.93 (调研结论):
- 调研时发现: 4 大工具 (Elicit/Consensus/Scite/Research Rabbit) 都用 1 段 prompt
  让 LLM 同时做 stance + 类型 + 引用抽取. 我合并为 1 个 agent, 节省 3 次 LLM 调用.
- 性能预算: 10 篇 1 次 LLM 调用 ~5-8s. 跟 critic_review 并发 (Semaphore=3) 持平.
- 失败兜底: stance = "unsure" / study_type = "other" / key_quote = "" 都不会让节点崩.
"""
import asyncio
import json
import logging
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.state import SearchState
from backend.utils.llm_client import call_llm
from backend.agents._step_helper import _step
from backend.agents._schemas import (
    parse_with_retry_async,
    _strip_markdown_fence,
)

logger = logging.getLogger(__name__)

# 最大评审论文数. 跟 synthesis 用的 10 对齐, 节省 token.
# 11-25 的论文只参与 critic 但不分类 (避免 LLM 上下文爆炸).
_MAX_CLASSIFY = 10

# 并发上限. 一次 LLM 调用, 不需要 Semaphore, 但 JSON 解析 / 兜底走串行.
_CLASSIFY_TIMEOUT = 30.0  # 节点级超时 (秒). 跟 search/expand 同步.

# 4 种合法 stance (Scite 风格). 聚合时也算入 "unsure" 兜底.
STANCE_VALUES = ("supporting", "contrasting", "neutral", "mixed", "unsure")

# 7 种常见 study_type (Consensus / Elicit 风格).
STUDY_TYPE_VALUES = (
    "rct",                # 随机对照试验
    "meta-analysis",      # 荟萃分析
    "systematic-review",  # 系统综述
    "review",             # 普通综述
    "survey",             # 调研 / 问卷
    "method",             # 方法论 (新算法 / 新框架)
    "case-study",         # 案例研究
    "empirical",          # 经验性研究
    "other",              # 兜底
)


class PaperClassify(BaseModel):
    """R10.5.93: 单篇论文 3 维分类 (stance + study_type + key_quote)."""
    stance: str = Field(default="unsure")
    study_type: str = Field(default="other")
    key_quote: str = Field(default="", max_length=300)

    @field_validator("stance")
    @classmethod
    def _validate_stance(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in STANCE_VALUES else "unsure"

    @field_validator("study_type")
    @classmethod
    def _validate_study_type(cls, v: str) -> str:
        v = (v or "").strip().lower()
        # 兼容 LLM 返回的 'randomized-controlled-trial' / 'rct' 等
        aliases = {
            "randomized-controlled-trial": "rct",
            "randomised-controlled-trial": "rct",
            "meta analysis": "meta-analysis",
            "systematic review": "systematic-review",
            "case study": "case-study",
            "empirical study": "empirical",
        }
        v = aliases.get(v, v)
        return v if v in STUDY_TYPE_VALUES else "other"


# RootModel: 顶层就是 dict[paper_id, PaperClassify]
class ClassifyBatchOutput(BaseModel):
    """R10.5.93: stance_classifier LLM 输出 schema.

    LLM 输出 {"<paper_id>": {stance, study_type, key_quote}, ...} 形式.
    RootModel 顶层就是 dict, 不用 .scores 二层访问.
    """
    root: dict[str, PaperClassify] = Field(default_factory=dict)


CLASSIFY_PROMPT_TEMPLATE = """你是一位学术文献分析师. 对以下论文列表, 一次性输出 3 维分类.

## 当前研究问题
{query}

## 论文列表 (按重要性排序, 1-based)
{papers_block}

## 分类要求

对每篇论文, 输出以下 3 个字段:

1. **stance** (立场): 这篇论文对当前研究问题的立场.
   - "supporting": 论文支持研究问题的核心假设 / 结论
   - "contrasting": 论文反对 / 反驳 / 提出不同结果
   - "neutral": 论文不直接回答, 仅做背景 / 综述
   - "mixed": 论文部分支持部分反对 (同时报告 positive + negative)
   - "unsure": 信息不足无法判断

2. **study_type** (研究类型):
   - "rct": 随机对照试验
   - "meta-analysis": 荟萃分析 (定量合并多项研究)
   - "systematic-review": 系统综述
   - "review": 普通综述 / narrative review
   - "survey": 调研 / 问卷研究
   - "method": 方法论文 (新算法 / 新框架 / 新模型)
   - "case-study": 案例研究 / 个案分析
   - "empirical": 经验性研究 (有数据 + 实验)
   - "other": 其它 (如纯理论)

3. **key_quote** (关键引用): 从该论文 abstract 抽取最能代表其核心发现的 1 句.
   - 必须是 abstract 中的原话 (或极接近原话)
   - 长度 30-200 字
   - 中英文都可, 保持原语言

## 输出格式 (严格 JSON)

{{
  "1": {{"stance": "supporting", "study_type": "empirical", "key_quote": "..."}},
  "2": {{"stance": "contrasting", "study_type": "rct", "key_quote": "..."}},
  ...
}}

JSON 顶层是 1-based 字符串 (不是 paper_id). 论文数 = papers_block 行数.
必须是合法 JSON, 不要 Markdown 围栏. 字段值必须严格匹配上面枚举."""


def _build_papers_block(papers: list[dict]) -> str:
    """把 ranked_papers 列表拼成 1-based 编号的 paper block."""
    blocks = []
    for i, p in enumerate(papers, 1):
        title = (p.get("title") or "无标题")[:120]
        abstract = (p.get("abstract") or "无摘要")[:300]
        blocks.append(
            f"[{i}] {title}\n"
            f"  Abstract: {abstract}"
        )
    return "\n\n".join(blocks)


def _build_consensus_summary(classifications: list[tuple[str, str]]) -> dict:
    """R10.5.93: 跨所有论文的立场聚合, 供前端 ConsensusMeter 显示.

    聚合维度:
    - supporting / contrasting / neutral / mixed / unsure 各自计数
    - majority_stance: 多数立场 (支持最多)
    - summary: 1 句话总结 (e.g. "7/10 papers support the hypothesis, 2 contradict")

    Args:
        classifications: [(stance, study_type), ...] 列表
    """
    counts = {s: 0 for s in STANCE_VALUES}
    type_counts: dict[str, int] = {}
    for stance, study_type in classifications:
        counts[stance] = counts.get(stance, 0) + 1
        type_counts[study_type] = type_counts.get(study_type, 0) + 1

    # 多数立场 (排除 unsure). 支持最多 = majority.
    # 只考虑有投票的 (count > 0), 避免 0 counts 时 max() 返回第一个 key.
    non_unsure = {k: v for k, v in counts.items() if k != "unsure" and v > 0}
    if non_unsure:
        majority_stance = max(non_unsure, key=non_unsure.get)
    else:
        # 全 unsure / 全 0 → majority 也是 unsure
        majority_stance = "unsure"

    total = len(classifications)
    sum_supp = counts.get("supporting", 0)
    sum_contra = counts.get("contrasting", 0)
    sum_mixed = counts.get("mixed", 0)
    sum_neutral = counts.get("neutral", 0)
    sum_unsure = counts.get("unsure", 0)

    # 1 句总结
    if total == 0:
        summary_text = "无分类结果"
    elif sum_supp > sum_contra + sum_mixed:
        summary_text = f"{sum_supp}/{total} 篇论文支持当前研究假设"
    elif sum_contra > sum_supp:
        summary_text = f"{sum_contra}/{total} 篇论文反对当前研究假设"
    elif sum_mixed >= max(sum_supp, sum_contra):
        summary_text = f"{sum_mixed}/{total} 篇论文报告混合结果 (同时支持 + 反对)"
    else:
        summary_text = f"文献立场分散: 支持 {sum_supp}, 反对 {sum_contra}, 中性 {sum_neutral}, 混合 {sum_mixed}"

    return {
        "total": total,
        "counts": counts,
        "type_counts": type_counts,
        "majority_stance": majority_stance,
        "summary": summary_text,
    }


async def classify_papers_node(state: SearchState) -> SearchState:
    """R10.5.93: 对 ranked_papers 一次性分类 (stance + study_type + key_quote).

    跟 critic_review 区别:
    - critic: 审稿人视角 (quality_score + 优缺点) — 决定是否推荐采纳
    - stance_classifier: 研究问题视角 (立场 + 类型 + 引用) — 决定文献支持/反对

    节点位置: rank → classify → critic → synthesize
    (插入到 critic 之前, 让 critic 看到分类结果作为参考)

    失败兜底: 单次 LLM 失败 → 全部论文 stance="unsure" + study_type="other" + key_quote=""
    这样前端依然能显示 (只是显示空), 不会让整条流水线崩.
    """
    ranked_papers = state.get("ranked_papers", []) or []
    if not ranked_papers:
        return state

    _step(state, "classify", f"🏷️ 启动 stance/study_type/quote 分类 · {len(ranked_papers)} papers")

    provider = state.get("provider")
    query = state.get("original_query", "") or ""
    papers_to_classify = ranked_papers[:_MAX_CLASSIFY]

    # 1) 1 次 LLM 调用, 批量输出所有论文的分类
    papers_block = _build_papers_block(papers_to_classify)
    prompt = CLASSIFY_PROMPT_TEMPLATE.format(
        query=query[:300],
        papers_block=papers_block,
    )

    logger.info(
        f"[stance_classifier] classifying {len(papers_to_classify)} papers "
        f"(max {_MAX_CLASSIFY}, query='{query[:50]}')"
    )

    try:
        parsed, usage = await asyncio.wait_for(
            parse_with_retry_async(
                call_llm=call_llm,
                prompt=prompt,
                schema=ClassifyBatchOutput,
                system="你是一位学术文献分析师, 严格按 JSON schema 输出.",
                max_tokens=2000,  # 10 篇 × 3 字段, 平均 200 字/篇
                task_type="fast",
                provider=provider,
                timeout=_CLASSIFY_TIMEOUT,
                retry_suffix="⚠️ 上次输出 JSON 格式不对, 请重新按 schema 输出 (1-based 数字 key).",
                log_tag="stance_classifier",
                base_usage=None,
            ),
            timeout=_CLASSIFY_TIMEOUT + 5.0,  # 留 retry buffer
        )
    except asyncio.TimeoutError:
        logger.warning(f"[stance_classifier] 节点超时 ({_CLASSIFY_TIMEOUT}s), 走兜底")
        parsed = None
        usage = None
    except Exception as e:
        logger.warning(f"[stance_classifier] LLM 调用失败: {type(e).__name__}: {e}, 走兜底")
        parsed = None
        usage = None

    # 2) 把 LLM 输出映射回 ranked_papers. LLM 用 1-based 数字 key, 我们按 index 还原.
    classifications_map: dict[str, dict] = {}  # paper_id → {stance, study_type, key_quote}
    classifications_pairs: list[tuple[str, str]] = []  # 用于聚合

    if parsed is not None and parsed.root:
        for i, paper in enumerate(papers_to_classify, 1):
            key = str(i)
            if key in parsed.root:
                c = parsed.root[key]
                classifications_map[paper.get("paper_id", "")] = {
                    "stance": c.stance,
                    "study_type": c.study_type,
                    "key_quote": c.key_quote[:300],
                }
                classifications_pairs.append((c.stance, c.study_type))
            else:
                # 缺这个 key → 兜底
                classifications_map[paper.get("paper_id", "")] = {
                    "stance": "unsure",
                    "study_type": "other",
                    "key_quote": "",
                }
                classifications_pairs.append(("unsure", "other"))
    else:
        # 整体失败: 所有论文都用兜底
        for paper in papers_to_classify:
            classifications_map[paper.get("paper_id", "")] = {
                "stance": "unsure",
                "study_type": "other",
                "key_quote": "",
            }
            classifications_pairs.append(("unsure", "other"))

    # 3) 把分类写回 ranked_papers (in-place dict mutation)
    updated_papers = []
    for paper in ranked_papers:
        pid = paper.get("paper_id", "")
        if pid in classifications_map:
            paper = dict(paper)  # 复制避免污染 cache
            paper["stance"] = classifications_map[pid]["stance"]
            paper["study_type"] = classifications_map[pid]["study_type"]
            paper["key_quote"] = classifications_map[pid]["key_quote"]
        updated_papers.append(paper)

    # 4) 聚合 consensus_summary
    consensus = _build_consensus_summary(classifications_pairs)

    # 5) 更新 cost (parse_with_retry 已 merge base_usage, 这里再 merge usage)
    from backend.utils.llm_client import merge_usage_into_state
    cost_update = merge_usage_into_state(state, usage) if usage else {}

    _step(
        state, "classify",
        f"✅ 分类完成 · {len(classifications_map)}/{len(papers_to_classify)} papers · "
        f"立场 {consensus['counts'].get('supporting', 0)}✓ / "
        f"{consensus['counts'].get('contrasting', 0)}✗ / "
        f"{consensus['counts'].get('mixed', 0)}≈ / "
        f"{consensus['counts'].get('neutral', 0)}·"
    )

    return {
        **state,
        **cost_update,
        "ranked_papers": updated_papers,
        "stance_summary": consensus,
    }
