"""utils.export — 学术引文格式导出 (BibTeX / RIS / EndNote)

R10.5 P0 (用户反馈): 学术工具的"杀手锏" — 用户从搜索结果一键
导入本地文献管理 (Zotero/Mendeley/EndNote/JabRef). 不需要 Zotero OAuth,
纯字符串拼接,前端一个 Download 按钮即可.

格式说明:
  - BibTeX: Zotero / JabRef / BibTeX 工具直接导入
  - RIS: EndNote / Mendeley / RefMan 通用
  - EndNote .enw: EndNote 专有
"""
from __future__ import annotations

import re
from typing import Iterable


# ===== BibTeX =====

def _sanitize_cite_key(text: str) -> str:
    """生成合法 BibTeX cite key: ASCII only + 保留 - _."""
    s = re.sub(r"[^A-Za-z0-9_-]+", "", text or "")
    return s or "unknown"


def _make_cite_key(paper: dict) -> str:
    """first_author_year_first_word 规则: 经典 BibTeX key 风格."""
    authors = paper.get("authors") or []
    first = (authors[0] if authors else "unknown").split()[-1].lower() if authors else "unknown"
    first = _sanitize_cite_key(first)
    year = str(paper.get("year") or "n.d.")
    title = paper.get("title") or ""
    # 标题第一个非空 word (跳过常见停用词)
    stop = {"a", "an", "the", "of", "in", "on", "for", "to", "and", "or", "with"}
    words = [w for w in re.findall(r"[A-Za-z]+", title) if w.lower() not in stop]
    title_word = words[0].lower() if words else "untitled"
    return _sanitize_cite_key(f"{first}{year}{title_word}")


def _escape_bibtex(text: str | None) -> str:
    """BibTeX 字段特殊字符转义: & % $ # _ { } ~ ^ \\."""
    if not text:
        return ""
    # 顺序很重要, 反斜杠先转
    out = str(text)
    out = out.replace("\\", r"\\")
    out = out.replace("{", r"\{").replace("}", r"\}")
    # & % $ # 都需要完整 LaTeX 转义
    for ch, esc in [("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_")]:
        out = out.replace(ch, esc)
    return out


def papers_to_bibtex(papers: Iterable[dict]) -> str:
    """生成完整 BibTeX 字符串.

    每篇论文转一条 @article 记录, cite key 全局唯一 (后缀 -1/-2).
    """
    entries: list[str] = []
    used_keys: set[str] = set()

    for p in papers:
        base_key = _make_cite_key(p)
        key = base_key
        n = 1
        while key in used_keys:
            n += 1
            key = f"{base_key}-{n}"
        used_keys.add(key)

        title = _escape_bibtex(p.get("title", ""))
        authors_str = " and ".join(_escape_bibtex(a) for a in (p.get("authors") or []))
        year = p.get("year") or ""
        venue = _escape_bibtex(p.get("venue", ""))
        url = p.get("url", "")
        doi = p.get("doi", "")
        # 评分作为 note 字段 (ScholarFlow 唯一数据)
        score = p.get("final_score", 0)
        note = f"ScholarFlow score: {score:.1f}/10"

        # 字段组装
        # P2-1 fix (深度审计 §P2-1): BibTeX 标题大小写保护.
        # 旧实现 `title = {title}` 让引用样式 (APA/IEEE) 自动改写大小写,
        # 学术工具导入时可能错误把 "BERT" 改成 "Bert". 用双层括号
        # `{{Deep Learning}}` 强制保留原始大小写.
        fields: list[str] = [
            f"  title     = {{{{{title}}}}}",
            f"  author    = {{{authors_str}}}",
        ]
        if year:
            fields.append(f"  year      = {{{year}}}")
        if venue:
            fields.append(f"  journal   = {{{venue}}}")
        if doi:
            fields.append(f"  doi       = {{{doi}}}")
        if url:
            fields.append(f"  url       = {{{url}}}")
        fields.append(f"  note      = {{{_escape_bibtex(note)}}}")

        entry = f"@article{{{key},\n" + ",\n".join(fields) + "\n}"
        entries.append(entry)

    return "\n\n".join(entries) + "\n"


# ===== RIS =====

def _escape_ris(text: str | None) -> str:
    """RIS 字段: 简单, 不用转义, 只 strip 控制字符."""
    if not text:
        return ""
    return re.sub(r"[\r\n]+", " ", str(text)).strip()


def papers_to_ris(papers: Iterable[dict]) -> str:
    """生成 RIS 字符串 (EndNote / Mendeley / RefMan 通用)."""
    lines: list[str] = []
    for p in papers:
        lines.append("TY  - JOUR")  # 期刊文章
        for author in (p.get("authors") or []):
            lines.append(f"AU  - {_escape_ris(author)}")
        if p.get("title"):
            lines.append(f"TI  - {_escape_ris(p.get('title'))}")
        if p.get("venue"):
            lines.append(f"JO  - {_escape_ris(p.get('venue'))}")
        if p.get("year"):
            lines.append(f"PY  - {p.get('year')}")
        if p.get("doi"):
            lines.append(f"DO  - {_escape_ris(p.get('doi'))}")
        if p.get("url"):
            lines.append(f"UR  - {_escape_ris(p.get('url'))}")
        if p.get("abstract"):
            lines.append(f"AB  - {_escape_ris(p.get('abstract'))}")
        lines.append("ER  - ")
    return "\n".join(lines) + "\n"
