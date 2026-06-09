"""Tests for utils.export — BibTeX / RIS 导出 (R10.5 P0).

覆盖:
  1. cite key 生成 (first_author_year_first_word)
  2. BibTeX 特殊字符转义 (& % $ # _ { } ~ ^ \\)
  3. cite key 冲突时 -1/-2 后缀
  4. RIS 字段映射 (TY/AU/TI/JO/PY/DO/UR/AB/ER)
  5. 空论文列表返空串
  6. 论文缺字段 (no authors / no title) 优雅降级
"""
from __future__ import annotations

import pytest

from backend.utils.export import (
    papers_to_bibtex,
    papers_to_ris,
    _make_cite_key,
    _sanitize_cite_key,
    _escape_bibtex,
)


# ===== _sanitize_cite_key =====

class TestSanitizeCiteKey:
    def test_strips_non_ascii(self):
        """中文 / 特殊字符应被替换成空."""
        assert _sanitize_cite_key("transformer & cnn 模型") == "transformercnn"

    def test_keeps_dash_underscore(self):
        assert _sanitize_cite_key("abc-123_xyz") == "abc-123_xyz"

    def test_empty_returns_unknown(self):
        assert _sanitize_cite_key("") == "unknown"

    def test_pure_special_returns_unknown(self):
        """纯特殊字符不应返空, fallback unknown."""
        assert _sanitize_cite_key("$$$") == "unknown"


# ===== _make_cite_key =====

class TestMakeCiteKey:
    def test_first_author_year_first_word(self):
        paper = {
            "authors": ["John Smith", "Alice"],
            "year": 2024,
            "title": "GraphRAG: A New Approach",
        }
        assert _make_cite_key(paper) == "smith2024graphrag"

    def test_no_authors_uses_unknown(self):
        assert _make_cite_key({"authors": [], "year": 2024, "title": "Test"}) == "unknown2024test"

    def test_skips_stop_words_in_title(self):
        """The / A / An 等停用词跳过, 第一个有意义 word 进 key."""
        paper = {
            "authors": ["Jane Doe"],
            "year": 2023,
            "title": "A Survey of Methods",
        }
        assert _make_cite_key(paper) == "doe2023survey"

    def test_chinese_title_falls_back_to_untitled(self):
        """中文标题无 ASCII word → 用 untitled."""
        paper = {
            "authors": ["张三"],
            "year": 2024,
            "title": "基于深度学习的图像识别",
        }
        key = _make_cite_key(paper)
        # 标题无 ASCII, 但 "depth" 也不在, fallback "untitled"
        # 实际: re.findall(r"[A-Za-z]+") 在中文里找不到, 用 untitled
        assert "untitled" in key or key == "zhang2024untitled"


# ===== _escape_bibtex =====

class TestEscapeBibtex:
    def test_escapes_specials(self):
        assert _escape_bibtex("a & b") == r"a \& b"
        assert _escape_bibtex("100%") == r"100\%"
        assert _escape_bibtex("$var") == r"\$var"
        assert _escape_bibtex("#1") == r"\#1"
        assert _escape_bibtex("snake_case") == r"snake\_case"

    def test_escapes_braces(self):
        assert _escape_bibtex("{a}") == r"\{a\}"

    def test_escapes_backslash_first(self):
        """反斜杠必须先于其他转义 (避免双重转义)."""
        assert _escape_bibtex(r"a\b") == r"a\\b"

    def test_none_returns_empty(self):
        assert _escape_bibtex(None) == ""

    def test_keeps_safe_text(self):
        assert _escape_bibtex("Hello World") == "Hello World"


# ===== papers_to_bibtex =====

class TestPapersToBibtex:
    def test_single_paper(self):
        paper = {
            "title": "Attention Is All You Need",
            "authors": ["Vaswani", "Shazeer"],
            "year": 2017,
            "venue": "NeurIPS",
            "url": "https://arxiv.org/abs/1706.03762",
            "final_score": 9.5,
        }
        out = papers_to_bibtex([paper])
        assert "@article{vaswani2017attention" in out
        assert "title     = {Attention Is All You Need}" in out
        assert "author    = {Vaswani and Shazeer}" in out
        assert "year      = {2017}" in out
        assert "journal   = {NeurIPS}" in out
        assert "url       = {https://arxiv.org/abs/1706.03762}" in out
        assert "ScholarFlow score: 9.5/10" in out
        assert out.endswith("\n")

    def test_cite_key_uniqueness(self):
        """2 篇同 author+year+title → key 加上 -1/-2 后缀."""
        paper = {
            "authors": ["X"],
            "year": 2024,
            "title": "Test Paper",
        }
        out = papers_to_bibtex([paper, paper, paper])
        # 3 个不同 key
        keys = [k for k in out.split("@article{")[1:]]
        assert "x2024test" in keys[0]
        assert "x2024test-2" in keys[1]
        assert "x2024test-3" in keys[2]

    def test_escaping_in_paper(self):
        paper = {
            "title": "RAG & Knowledge Graphs: 100% Coverage",
            "authors": ["Smith & Jones"],  # 作者也含特殊字符
            "year": 2024,
        }
        out = papers_to_bibtex([paper])
        assert r"title     = {RAG \& Knowledge Graphs: 100\% Coverage}" in out
        assert r"author    = {Smith \& Jones}" in out

    def test_empty_list(self):
        # 空列表返空串或纯 \n, 都视为"无内容" (无 @article 记录)
        assert papers_to_bibtex([]).strip() == ""

    def test_missing_fields_graceful(self):
        """缺 authors / title / year / venue 不抛异常."""
        paper = {"paper_id": "x"}  # 几乎全空
        out = papers_to_bibtex([paper])
        # 仍能生成 (title 为空, author 为空, year 为空, 都不出字段)
        assert "@article{" in out
        assert "note      = " in out  # 至少 note 字段有


# ===== papers_to_ris =====

class TestPapersToRis:
    def test_ris_format(self):
        paper = {
            "title": "Test Paper",
            "authors": ["Alice", "Bob"],
            "year": 2024,
            "venue": "ICML",
            "doi": "10.1234/test",
            "url": "https://example.com",
        }
        out = papers_to_ris([paper])
        assert "TY  - JOUR" in out
        assert "AU  - Alice" in out
        assert "AU  - Bob" in out
        assert "TI  - Test Paper" in out
        assert "JO  - ICML" in out
        assert "PY  - 2024" in out
        assert "DO  - 10.1234/test" in out
        assert "UR  - https://example.com" in out
        assert "ER  - " in out

    def test_ris_strips_newlines_in_abstract(self):
        """摘要里换行应替换成空格 (RIS 字段单行)."""
        paper = {"title": "T", "abstract": "Line 1\nLine 2\nLine 3"}
        out = papers_to_ris([paper])
        assert "AB  - Line 1 Line 2 Line 3" in out
        assert "AB  - Line 1\nLine 2" not in out

    def test_ris_empty(self):
        # 空列表返空串或纯 \n, 都视为"无内容" (无 TY 记录)
        assert papers_to_ris([]).strip() == ""
