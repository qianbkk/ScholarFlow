"""测试 backend/api/ 下的纯解析/构造函数。

Semantic Scholar / OpenAlex 客户端的解析逻辑大部分内联在 search_papers()
异步函数里（与网络 IO 耦合），因此这里只测试：

  1. 纯函数：OpenAlex 的 _reconstruct_abstract（倒排索引 → 原文）
  2. Mock 模式下的 search_papers 行为（用 force_mock_api fixture 切到 mock）
  3. mock_data 中的 paper_id 唯一性（防止 BUG-MEDIUM-005 重复）

完全无网络依赖。
"""
import pytest
import asyncio

from backend.api.openalex import _reconstruct_abstract
from backend.models.paper import Paper


# ===== 纯函数：OpenAlex 倒排索引 → 摘要原文 =====

def test_openalex_reconstruct_abstract_simple():
    """倒排索引 {"the": [0, 2], "cat": [1]} → "the cat the" """
    inverted = {"the": [0, 2], "cat": [1]}
    assert _reconstruct_abstract(inverted) == "the cat the"


def test_openalex_reconstruct_abstract_empty():
    """空 dict / None → 空字符串"""
    assert _reconstruct_abstract({}) == ""
    assert _reconstruct_abstract(None) == ""


def test_openalex_reconstruct_abstract_positions_unsorted():
    """位置乱序输入也应按位置升序重建"""
    inverted = {"z": [2], "a": [0], "m": [1]}
    assert _reconstruct_abstract(inverted) == "a m z"


# ===== Mock 模式：Semantic Scholar search_papers =====

def test_ss_search_papers_mock_returns_papers(force_mock_api):
    """Mock 模式下 search_papers 返回 Paper 对象列表"""
    from backend.api.semantic_scholar import search_papers
    papers = asyncio.run(search_papers("transformer", limit=5))
    assert isinstance(papers, list)
    assert len(papers) > 0
    assert all(isinstance(p, Paper) for p in papers)


def test_ss_search_papers_mock_fields(force_mock_api):
    """Mock 论文关键字段都已填好"""
    from backend.api.semantic_scholar import search_papers
    papers = asyncio.run(search_papers("transformer", limit=3))
    for p in papers:
        assert p.paper_id  # 非空
        assert p.title  # 非空
        assert isinstance(p.authors, list)
        assert isinstance(p.year, int)
        assert p.year >= 1990
        assert p.source == "semantic_scholar"


def test_ss_search_papers_mock_respects_limit(force_mock_api):
    """limit=3 最多返回 3 篇"""
    from backend.api.semantic_scholar import search_papers
    papers = asyncio.run(search_papers("transformer", limit=3))
    assert len(papers) <= 3


# ===== Mock 模式：OpenAlex search_papers =====

def test_openalex_search_papers_mock_returns_papers(force_mock_api):
    """Mock 模式下 OpenAlex 搜索返回 Paper 列表"""
    from backend.api.openalex import search_papers
    papers = asyncio.run(search_papers("transformer", limit=5))
    assert isinstance(papers, list)
    for p in papers:
        assert isinstance(p, Paper)
        # OpenAlex 来源
        assert p.source == "openalex"


def test_openalex_search_papers_mock_has_abstract(force_mock_api):
    """Mock 模式下 OpenAlex 论文应有非空 abstract

    用 'neural' query（mock 中既有 semantic_scholar 也有 openalex 命中）
    """
    from backend.api.openalex import search_papers
    papers = asyncio.run(search_papers("neural", limit=10))
    assert len(papers) > 0, "应至少返回一篇 openalex 论文"
    papers_with_abstract = [p for p in papers if p.abstract]
    assert len(papers_with_abstract) > 0, "至少应有部分论文带 abstract"


# ===== Mock 数据的 paper_id 唯一性（防 BUG-MEDIUM-005） =====

def test_mock_paper_ids_unique():
    """get_mock_papers 返回的所有 paper_id 应唯一"""
    from backend.api.mock_data import get_mock_papers
    papers = get_mock_papers("", limit=200)
    ids = [p.paper_id for p in papers]
    duplicates = [i for i in ids if ids.count(i) > 1]
    assert len(ids) == len(set(ids)), f"重复 paper_id: {set(duplicates)}"


def test_get_all_mock_papers_unique():
    """get_all_mock_papers 的 paper_id 也应唯一"""
    from backend.api.mock_data import get_all_mock_papers
    papers = get_all_mock_papers()
    ids = [p.paper_id for p in papers]
    assert len(ids) == len(set(ids)), f"重复 paper_id: {[i for i in ids if ids.count(i) > 1]}"


def test_get_all_mock_papers_has_papers():
    """_MOCK_PAPERS 数据集非空"""
    from backend.api.mock_data import get_all_mock_papers
    papers = get_all_mock_papers()
    assert len(papers) > 10  # 至少应有 10+ 篇基础论文


# ===== Paper dataclass 健全性 =====

def test_paper_default_values():
    """Paper dataclass 缺省值正确"""
    p = Paper()
    assert p.paper_id == ""
    assert p.title == ""
    assert p.year == 0
    assert p.authors == []
    assert p.is_expanded is False
    assert p.relevance_score == 0.0


def test_paper_to_dict_roundtrip():
    """to_dict → from_dict 应保留所有关键字段"""
    p = Paper(
        paper_id="x1",
        title="T",
        year=2020,
        authors=["A", "B"],
        citation_count=42,
    )
    d = p.to_dict()
    p2 = Paper.from_dict(d)
    assert p2.paper_id == "x1"
    assert p2.title == "T"
    assert p2.year == 2020
    assert p2.authors == ["A", "B"]
    assert p2.citation_count == 42
