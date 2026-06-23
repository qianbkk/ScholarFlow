"""Paper dataclass — unified representation across v1 (LangGraph) and v3 (mock).

Moved from backend.models.paper so both backends can import it without
creating a dependency on backend.models (which carries LangGraph-only
SearchState + PipelineStatus types).
"""
from dataclasses import dataclass, field
from typing import Literal, Optional


# PaperSource literal — covers all known paper origins across v1 + v3.
# v1 backend often stores raw source strings ("semantic_scholar", "openalex",
# "arxiv", "pubmed", "crossref", "synthesis"); v3 narrows to 4 with a default.
PaperSource = Literal[
    "semantic_scholar",
    "openalex",
    "arxiv",
    "pubmed",
    "crossref",
    "local_demo",
    "synthesis",
]


# to_dict / 反序列化时保留的有效字段
# P2-7 fix (深度审计 §P2-7): _scored 必须加入 _PAPER_FIELDS,
# 否则跨迭代 refine → search 时 Paper.from_dict() 反序列化丢失 _scored,
# 第二轮 rank 全部论文被重评浪费 LLM token. Round 2 PERF-006 缓存失效.
# R10.5.93 (升级 1/3/4): 加 stance + study_type + key_quote, 供 stance_classifier
# 节点写入, 前端 PaperList / SearchSummary / ReportView 读取显示.
_PAPER_FIELDS = (
    "paper_id", "title", "abstract", "year", "authors", "citation_count",
    "venue", "doi", "url", "source", "is_expanded", "is_fallback",
    "relevance_score", "authority_score", "consistency_score", "final_score",
    "references", "_scored",
    "stance", "study_type", "key_quote",
)


@dataclass
class Paper:
    paper_id: str = ""
    title: str = ""
    abstract: str = ""
    year: int = 0
    authors: list[str] = field(default_factory=list)
    citation_count: int = 0
    venue: str = ""
    doi: str = ""
    url: str = ""
    source: str = ""
    is_expanded: bool = False
    # C5 修复：当 API 真实调用失败、降级到 mock 数据时，标记 is_fallback=True。
    # 前端 QueryPanel 可据此显示警告 banner，告知用户当前结果是 fallback 模拟数据。
    is_fallback: bool = False

    # 由 RankerAgent 填写
    relevance_score: float = 0.0
    authority_score: float = 0.0
    consistency_score: float = 0.0
    final_score: float = 0.0

    # Fix-X13: 显式区分"未评分"和"评分为 0". 旧版 ranker 用 ==0 跨迭代
    # 缓存, 真无关论文 (rel=0.0) 会被第二轮回炉重评浪费 LLM token.
    #  True = 本轮已 LLM 评过分 (即使 rel=0);  False = 待评.
    _scored: bool = False

    # 引用关系（用于图谱构建）
    references: list[str] = field(default_factory=list)

    # R10.5.93 (升级 1/3/4): stance_classifier 节点写入, 前端消费.
    # stance: "supporting" | "contrasting" | "neutral" | "mixed" | "unsure"
    # study_type: "rct" | "meta-analysis" | "systematic-review" | "review" |
    #             "survey" | "method" | "case-study" | "empirical" | "other"
    # key_quote: 1 句关键引用, ≤ 300 字
    stance: str = ""
    study_type: str = ""
    key_quote: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _PAPER_FIELDS}

    @classmethod
    def from_dict(cls, d: dict) -> "Paper":
        """从 dict 安全构造 Paper，未知字段忽略。"""
        return cls(**{k: v for k, v in d.items() if k in _PAPER_FIELDS})

    def brief(self) -> str:
        """用于 LLM 提示词的简短描述。"""
        authors_str = ", ".join(self.authors[:3])
        if len(self.authors) > 3:
            authors_str += " et al."
        return (
            f"Title: {self.title}\n"
            f"Year: {self.year} | Citations: {self.citation_count} | Venue: {self.venue}\n"
            f"Authors: {authors_str}\n"
            f"Abstract: {self.abstract[:300]}..."
        )


# Re-exported by backend.models.paper for backward compat