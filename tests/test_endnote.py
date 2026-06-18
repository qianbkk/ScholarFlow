"""Tests for utils.endnote — EndNote XML 导出 (R10.5.40 Phase 5).

覆盖:
  1. 空论文列表 → 空 <records></records> body (仍 valid XML)
  2. year=0 → <year/>
  3. title 含 < → &lt; (XML 转义)
  4. 单 token author "J. Devlin" → "Devlin, J." (反向格式)
  5. DOI → <keywords><keyword>doi:...</keyword></keywords>
  6. (bonus) URL → <urls><related-urls><url>...</url></related-urls></urls>
  7. (bonus) ref-type "17" 始终出现, EndNote 必填
  8. (bonus) Paper dataclass + dict 输入都支持
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from backend.utils.endnote import (
    to_endnote_xml,
    papers_to_endnote_xml,
    _xml_escape,
    _format_author,
)
from backend.utils.export import (
    to_endnote_xml as export_to_endnote_xml,
    papers_to_endnote_xml as export_papers_to_endnote_xml,
)
from backend.models.paper import Paper


# ===== Empty list =====

class TestEmptyList:
    def test_empty_records_body(self):
        """空论文列表 → <records></records> body, 仍是合法 XML."""
        out = to_endnote_xml([])
        assert "<records>" in out
        assert "</records>" in out
        # body 必须为空 (record 之间)
        body = out.split("<records>")[1].split("</records>")[0]
        # 不应有 <record> 元素
        assert "<record>" not in body

    def test_empty_parses_as_valid_xml(self):
        out = to_endnote_xml([])
        # 不抛异常 + root 标签正确
        root = ET.fromstring(out)
        assert root.tag == "xml"
        records = root.findall("records")
        assert len(records) == 1
        assert records[0].findall("record") == []


# ===== Year = 0 / missing =====

class TestYearHandling:
    def test_year_zero_renders_empty_tag(self):
        """year=0 → <year/>, 不写数字."""
        paper = {"title": "T", "authors": ["A"], "year": 0}
        out = to_endnote_xml([paper])
        assert "<year/>" in out
        # 没有 <year>0</year>
        assert "<year>0</year>" not in out

    def test_year_missing_renders_empty_tag(self):
        """year 字段缺失 (None) → <year/>."""
        paper = {"title": "T", "authors": ["A"]}  # 无 year
        out = to_endnote_xml([paper])
        assert "<year/>" in out

    def test_year_normal_value(self):
        """year=2020 → <year>2020</year>."""
        paper = {"title": "T", "authors": ["A"], "year": 2020}
        out = to_endnote_xml([paper])
        assert "<year>2020</year>" in out


# ===== XML escaping =====

class TestXmlEscape:
    def test_title_with_less_than(self):
        """title 含 < → 转义成 &lt;."""
        paper = {
            "title": "Models < Transformers",
            "authors": ["A"],
            "year": 2024,
        }
        out = to_endnote_xml([paper])
        # 元素文本必须是转义后的
        assert "Models &lt; Transformers" in out
        # 原始 "<" (后面跟空格) 不应出现
        assert "Models < Transformers" not in out

    def test_title_with_ampersand(self):
        """title 含 & → &amp;."""
        paper = {"title": "RAG & KG", "authors": ["A"], "year": 2024}
        out = to_endnote_xml([paper])
        assert "RAG &amp; KG" in out
        assert "RAG & KG" not in out

    def test_abstract_with_quote(self):
        """abstract 含 " → &quot;."""
        paper = {
            "title": "T",
            "authors": ["A"],
            "year": 2024,
            "abstract": 'He said "hello"',
        }
        out = to_endnote_xml([paper])
        assert "He said &quot;hello&quot;" in out

    def test_xml_parses_without_error(self):
        """所有特殊字符组合仍能 ET.fromstring 解析."""
        paper = {
            "title": "A < B & C > D",
            "authors": ["Smith & Jones"],
            "year": 2024,
            "abstract": '"quotes" and \'apostrophes\' <ok>',
        }
        out = to_endnote_xml([paper])
        # 必须能解析, 不抛
        root = ET.fromstring(out)
        record = root.findall("records/record")[0]
        title_text = record.find("titles/title").text
        assert title_text == "A < B & C > D"


# ===== Author formatting =====

class TestAuthorFormatting:
    def test_single_token_becomes_lastname_only(self):
        """'J. Devlin' 是首字母缩写 + 姓, 反转为 'Devlin, J.'."""
        assert _format_author("J. Devlin") == "Devlin, J."

    def test_first_last_format(self):
        """'John Smith' → 'Smith, John'."""
        assert _format_author("John Smith") == "Smith, John"

    def test_already_lastname_firstname_passthrough(self):
        """已经是 'Lastname, Firstname' 格式 → 原样返回."""
        assert _format_author("Smith, John") == "Smith, John"

    def test_three_part_name(self):
        """'John Michael Smith' → 'Smith, John Michael'."""
        assert _format_author("John Michael Smith") == "Smith, John Michael"

    def test_empty_author_returns_empty(self):
        assert _format_author("") == ""
        assert _format_author(None) == ""

    def test_author_escapes_xml(self):
        """author 含 & → 转义.
        'Smith & Jones' 走 split() 得 3 tokens ['Smith', '&', 'Jones'],
        反转为 'Jones, Smith &' → 转义后 'Jones, Smith &amp;'.
        """
        paper = {
            "title": "T",
            "authors": ["Smith & Jones"],
            "year": 2024,
        }
        out = to_endnote_xml([paper])
        assert "<author>Jones, Smith &amp;</author>" in out


# ===== DOI in keywords =====

class TestDoiInKeywords:
    def test_doi_appears_as_keyword(self):
        """DOI 没专属字段, 落 <keywords><keyword>doi:...</keyword></keywords>."""
        paper = {
            "title": "T",
            "authors": ["A"],
            "year": 2024,
            "doi": "10.1234/test",
        }
        out = to_endnote_xml([paper])
        assert "<keywords>" in out
        assert "<keyword>doi:10.1234/test</keyword>" in out
        assert "</keywords>" in out

    def test_no_doi_no_keywords_element(self):
        """无 DOI → 不应有 <keywords> 元素."""
        paper = {"title": "T", "authors": ["A"], "year": 2024}
        out = to_endnote_xml([paper])
        assert "<keywords>" not in out
        assert "<keyword>" not in out

    def test_doi_parses_to_correct_keyword_text(self):
        """ElementTree 解析后, keyword 文本 == 'doi:...'."""
        paper = {
            "title": "T",
            "authors": ["A"],
            "year": 2024,
            "doi": "10.1109/foo.2024",
        }
        out = to_endnote_xml([paper])
        root = ET.fromstring(out)
        record = root.findall("records/record")[0]
        keywords = record.findall("keywords/keyword")
        assert len(keywords) == 1
        assert keywords[0].text == "doi:10.1109/foo.2024"


# ===== URL handling (bonus) =====

class TestUrlHandling:
    def test_url_in_related_urls(self):
        """URL → <urls><related-urls><url>...</url></related-urls></urls>."""
        paper = {
            "title": "T",
            "authors": ["A"],
            "year": 2024,
            "url": "https://arxiv.org/abs/2401.01234",
        }
        out = to_endnote_xml([paper])
        assert "<urls>" in out
        assert "<related-urls>" in out
        assert "<url>https://arxiv.org/abs/2401.01234</url>" in out

    def test_no_url_no_urls_element(self):
        paper = {"title": "T", "authors": ["A"], "year": 2024}
        out = to_endnote_xml([paper])
        assert "<urls>" not in out
        assert "<url>" not in out


# ===== ref-type =====

class TestRefType:
    def test_ref_type_always_present(self):
        """EndNote 强制 <ref-type>, 缺失会报错. 验证 '17' 始终出现."""
        paper = {"title": "T", "authors": ["A"]}
        out = to_endnote_xml([paper])
        assert '<ref-type name="Journal Article">17</ref-type>' in out

    def test_ref_type_attribute_parsing(self):
        """XML 解析后 ref-type 的属性 + 文本值正确."""
        paper = {"title": "T", "authors": ["A"]}
        out = to_endnote_xml([paper])
        root = ET.fromstring(out)
        record = root.findall("records/record")[0]
        ref_type = record.find("ref-type")
        assert ref_type is not None
        assert ref_type.attrib["name"] == "Journal Article"
        assert ref_type.text == "17"


# ===== Input type compatibility =====

class TestInputTypes:
    def test_paper_dataclass_input(self):
        """backend.models.Paper 对象 (有 dataclass 属性) 也能转."""
        p = Paper(
            title="Test",
            authors=["Alice"],
            year=2024,
            venue="ICML",
        )
        out = to_endnote_xml([p])
        assert "<title>Test</title>" in out
        assert "<author>Alice</author>" in out
        assert "<year>2024</year>" in out

    def test_dict_input(self):
        """纯 dict 输入 (前端 mock 格式)."""
        p = {"title": "T", "authors": ["A"], "year": 2024}
        out = to_endnote_xml([p])
        assert "<title>T</title>" in out

    def test_mixed_input(self):
        """Paper + dict 混用."""
        paper_obj = Paper(title="Obj", authors=["X"], year=2024)
        paper_dict = {"title": "Dict", "authors": ["Y"], "year": 2023}
        out = to_endnote_xml([paper_obj, paper_dict])
        assert "<title>Obj</title>" in out
        assert "<title>Dict</title>" in out


# ===== Export re-exports =====

class TestReExports:
    def test_export_module_alias(self):
        """backend.utils.export 也暴露 to_endnote_xml (跟 papers_to_bibtex 同 pattern)."""
        paper = {"title": "T", "authors": ["A"], "year": 2024}
        a = to_endnote_xml([paper])
        b = export_to_endnote_xml([paper])
        assert a == b
        c = export_papers_to_endnote_xml([paper])
        assert c == a

    def test_alias_papers_to_endnote_xml(self):
        paper = {"title": "T", "authors": ["A"], "year": 2024}
        a = to_endnote_xml([paper])
        b = papers_to_endnote_xml([paper])
        assert a == b


# ===== Realistic multi-paper =====

class TestRealisticScenario:
    def test_three_papers_with_varied_fields(self):
        """3 篇 paper, 字段参差不齐, 整体 XML 合法."""
        papers = [
            {
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani", "Noam Shazeer"],
                "year": 2017,
                "venue": "NeurIPS",
                "url": "https://arxiv.org/abs/1706.03762",
                "doi": "10.48550/arXiv.1706.03762",
            },
            {
                "title": "GPT-4 Technical Report",
                "authors": ["OpenAI"],
                "year": 2023,
                "venue": "arXiv",
                "url": "https://arxiv.org/abs/2303.08774",
            },
            {
                "title": "Pre-Print <Draft>",
                "authors": ["J. Devlin"],
                "year": 0,  # 未发表
                "abstract": "Pre-publication & ongoing work",
            },
        ]
        out = to_endnote_xml(papers)

        # 必须能解析
        root = ET.fromstring(out)
        records = root.findall("records/record")
        assert len(records) == 3

        # paper 1: 全字段
        r0 = records[0]
        assert r0.find("titles/title").text == "Attention Is All You Need"
        assert r0.find("year").text == "2017"
        authors = r0.findall("contributors/authors/author")
        assert authors[0].text == "Vaswani, Ashish"
        assert authors[1].text == "Shazeer, Noam"
        assert r0.find("urls/related-urls/url").text == "https://arxiv.org/abs/1706.03762"
        keywords = r0.findall("keywords/keyword")
        assert keywords[0].text == "doi:10.48550/arXiv.1706.03762"

        # paper 3: 转义 + year=0 + 单 token author
        r2 = records[2]
        # ElementTree 自动反转义, 拿回原值
        assert r2.find("titles/title").text == "Pre-Print <Draft>"
        # year=0 → ElementTree 看到 <year/> 没 text
        assert r2.find("year").text is None
        # author "J. Devlin" → "Devlin, J."
        authors2 = r2.findall("contributors/authors/author")
        assert authors2[0].text == "Devlin, J."