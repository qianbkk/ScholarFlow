"""Paper 数据类 — 跨 API 统一的论文表示。"""
from dataclasses import dataclass, field
from typing import Optional


# to_dict / 反序列化时保留的有效字段
_PAPER_FIELDS = (
    "paper_id", "title", "abstract", "year", "authors", "citation_count",
    "venue", "doi", "url", "source", "is_expanded",
    "relevance_score", "authority_score", "consistency_score", "final_score",
    "references",
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

    # 由 RankerAgent 填写
    relevance_score: float = 0.0
    authority_score: float = 0.0
    consistency_score: float = 0.0
    final_score: float = 0.0

    # 引用关系（用于图谱构建）
    references: list[str] = field(default_factory=list)

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
