"""T6 修复: _to_paper fallback URL 不再用 split('_')[-1] 拼 arxiv URL

之前: paper_id="ss_999_nonexistent" → split('_')[-1] = "nonexistent"
     → "https://arxiv.org/abs/nonexistent" (404)

修复: 走 Semantic Scholar 搜索链接, 任何 paper_id 都得到有效 URL
"""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
import sys
sys.path.insert(0, '.')

import pytest
from backend.api.mock_data import _to_paper, _PAPER_URL_MAP


def test_fallback_uses_semantic_scholar_search_not_arxiv():
    """未在 _PAPER_URL_MAP 收录的 ss_ id 必须用 Semantic Scholar 搜索链接。"""
    # 找一个不存在的 paper_id
    fake = {
        "paper_id": "ss_999_nonexistent_paper",
        "title": "Fake Paper",
        "year": 2024,
        "authors": ["John Doe"],
        "venue": "arXiv",
        "citation_count": 0,
        "abstract": "Test",
    }
    assert fake["paper_id"] not in _PAPER_URL_MAP
    paper = _to_paper(fake)
    assert "arxiv.org/abs/nonexistent" not in paper.url, (
        f"fallback URL 不应拼出 'arxiv.org/abs/nonexistent' (split bug), got: {paper.url}"
    )
    assert "semanticscholar.org/search" in paper.url, (
        f"ss_ paper_id fallback 应走 Semantic Scholar 搜索, got: {paper.url}"
    )


def test_known_paper_uses_real_arxiv_id():
    """已在 _PAPER_URL_MAP 中的 paper 必须用真实 arxiv ID。"""
    p = _to_paper({
        "paper_id": "ss_001_transformer",
        "title": "Attention Is All You Need",
        "year": 2017,
        "authors": [],
        "venue": "NeurIPS",
        "citation_count": 0,
        "abstract": "",
    })
    assert p.url == "https://arxiv.org/abs/1706.03762"
    assert "transformer" not in p.url  # 不是 fallback 的错误拼法


def test_openalex_id_fallback():
    """非 ss_ 前缀 id 应走 openalex.org 链接。"""
    p = _to_paper({
        "paper_id": "W123456789",
        "title": "OpenAlex Paper",
        "year": 2024,
        "authors": [],
        "venue": "",
        "citation_count": 0,
        "abstract": "",
    })
    assert p.url == "https://openalex.org/W123456789"


if __name__ == "__main__":
    test_fallback_uses_semantic_scholar_search_not_arxiv()
    test_known_paper_uses_real_arxiv_id()
    test_openalex_id_fallback()
    print("=== T6 fallback URL tests pass ===")
