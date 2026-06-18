"""utils.endnote — EndNote XML 导出 (R10.5.40 Phase 5: Agent 4)

EndNote XML 是 EndNote 桌面版导入自定义引文库的事实标准格式。
输出**完整字符串**, 前端拿去做 Blob 下载 (或后端写 .xml 文件).

参考格式 (EndNote X9 / X20 XML):
    <?xml version="1.0" encoding="UTF-8"?>
    <xml><records>
      <record>
        <ref-type name="Journal Article">17</ref-type>
        <contributors><authors><author>Lastname, Firstname</author></authors></contributors>
        <titles><title>...</title></titles>
        <year>2020</year>
        <volume>...</volume>
        <pages>...</pages>
        <urls><related-urls><url>...</url></related-urls></urls>
        <keywords><keyword>...</keyword></keywords>
        <abstract>...</abstract>
      </record>
    </records></xml>

注意:
  - ref-type 数值 17 = "Journal Article", 兼容 arXiv 预印本.
  - XML 特殊字符 (< > & " ') 必须转义, 否则 EndNote 导入报错.
  - 作者 "Lastname, Firstname" 格式; 单 token "J. Devlin" → "Devlin, J.".
  - DOI 没有专属字段, 用 <keywords><keyword>doi:...</keyword></keywords> 落.
"""
from __future__ import annotations

from html import escape as _html_escape
from typing import Iterable, List, Union

# 让 API 接受 Paper 对象或纯 dict — 后端 agent 传 Paper, 前端 mock 传 dict.
# 用 duck typing 拿属性, 不强制 isinstance 避免循环 import.
_PaperLike = Union["object", dict]


# ===== XML 工具 =====
# EndNote XML 用标准 XML 1.0 转义: < > & " '.
# Python stdlib `html.escape` 默认转义 < > & ", 默认 quote=True 也转义 '.
# 但 EndNote 解析器只关心 < > &, 我们额外覆盖 " ' 防 edge case.

def _xml_escape(text: str | None) -> str:
    """XML 1.0 转义 (< > & " '). None / 空串原样返回."""
    if text is None:
        return ""
    return _html_escape(str(text), quote=True)


def _format_author(author: str | None) -> str:
    """EndNote author 格式: "Lastname, Firstname".

    EndNote 期望 "Lastname, Firstname". 但 OpenAlex / Semantic Scholar 常返
    "J. Devlin" 这种"首字母缩写 + 姓" 格式. 我们检测:
      - 含逗号 → 已是 "Lastname, Firstname", 原样返回.
      - 含空格 → "Firstname Lastname", 反转为 "Lastname, Firstname".
      - 单 token (无空格) → 当作姓, 加逗号留空 firstname: "Lastname, ".
        但 EndNote 不喜欢空 firstname, 所以单 token 视作 already-lastname,
        仍走 "Token, " 形式.
      - 中文名 / 拉丁名混排 → 不反转, 简单尝试按最后一个空格切.
    """
    if not author:
        return ""
    a = str(author).strip()
    if not a:
        return ""
    # 已是 "Lastname, Firstname" (含逗号且逗号前有非空内容)
    if "," in a:
        return _xml_escape(a)
    # 按空格切
    parts = a.split()
    if len(parts) >= 2:
        last = parts[-1]
        firsts = " ".join(parts[:-1])
        return _xml_escape(f"{last}, {firsts}")
    # 单 token — "J." 或 "Devlin" 都直接返 (EndNote 容错)
    return _xml_escape(a)


# ===== 主函数 =====

def to_endnote_xml(papers: Iterable[_PaperLike]) -> str:
    """把 Paper 列表转 EndNote XML 字符串.

    每篇一个 <record>, 字段缺失时该字段省略 (但保留 ref-type, EndNote 必填).

    输入支持:
      - backend.models.Paper 对象 (用 getattr 拿字段)
      - dict (兼容前端 mock + 已有 BibTeX/RIS 测试)
      - 混合列表
    """
    records: List[str] = []

    for p in papers:
        records.append(_render_record(p))

    body = "\n".join(records)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xml><records>\n'
        f'{body}\n'
        '</records></xml>\n'
    )


def _get(p: _PaperLike, key: str, default=None):
    """统一 Paper / dict 取值."""
    if isinstance(p, dict):
        return p.get(key, default)
    return getattr(p, key, default)


def _render_record(p: _PaperLike) -> str:
    """单篇 <record>...</record> 字符串 (不含外层 wrapper)."""
    title = _get(p, "title", "") or ""
    abstract = _get(p, "abstract", "") or ""
    year = _get(p, "year", 0) or 0
    venue = _get(p, "venue", "") or ""
    doi = _get(p, "doi", "") or ""
    url = _get(p, "url", "") or ""
    authors = _get(p, "authors", []) or []

    parts: List[str] = []
    # ref-type "17" = Journal Article, arXiv 预印本 EndNote 也归 Journal Article.
    # EndNote 解析器依赖这个数值字段, 不能省略.
    parts.append('<ref-type name="Journal Article">17</ref-type>')

    # authors
    if authors:
        author_lines = "\n".join(
            f"        <author>{_format_author(a)}</author>"
            for a in authors
        )
        parts.append(
            "      <contributors><authors>\n"
            f"{author_lines}\n"
            "      </authors></contributors>"
        )
    else:
        parts.append("<contributors><authors></authors></contributors>")

    # titles
    parts.append(f"      <titles><title>{_xml_escape(title)}</title></titles>")

    # year: 0 或缺失 → 空标签 <year/>
    if year and int(year) > 0:
        parts.append(f"      <year>{int(year)}</year>")
    else:
        parts.append("      <year/>")

    # journal / volume — Paper 模型没 volume 字段, 简化为 journal=venue.
    # EndNote <journal> 是推荐字段, EndNote 导入后会用 venue 作 journal 名.
    # 保留 <volume/> 空标签作占位 (XML schema 容许空标签).
    parts.append(f"      <volume>{_xml_escape(venue)}</volume>")
    parts.append("      <pages/>")

    # urls
    if url:
        parts.append(
            "      <urls><related-urls>\n"
            f"        <url>{_xml_escape(url)}</url>\n"
            "      </related-urls></urls>"
        )

    # keywords (DOI 没有专属字段, 落 keyword)
    if doi:
        parts.append(
            "      <keywords>\n"
            f"        <keyword>doi:{_xml_escape(doi)}</keyword>\n"
            "      </keywords>"
        )

    # abstract
    if abstract:
        parts.append(f"      <abstract>{_xml_escape(abstract)}</abstract>")

    inner = "\n".join(parts)
    return f"  <record>\n{inner}\n  </record>"


# ===== 便捷别名 (跟 BibTeX / RIS 命名风格统一) =====

papers_to_endnote_xml = to_endnote_xml