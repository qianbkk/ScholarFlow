"""
节点 ⑥ — 综述报告生成
基于排序后的论文，生成结构化 Markdown 综述。
"""
import html
import re

from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state
from backend.utils.sanitize import wrap_user_input, isolation_system_suffix


SYSTEM = (
    "你是一位资深科研助手，熟悉学术文献分析和综述写作。"
    "请用中文输出，论文名保持英文原文。"
)


def _fallback_report(query: str, ranked: list[dict]) -> str:
    """LLM 不可用时的极简报告兜底。"""
    lines = [
        f"## 研究概述",
        f"针对查询「{query}」，本次检索从 Semantic Scholar 与 OpenAlex 双源汇总后，"
        f"经三维质检排序返回 Top {len(ranked)} 篇相关论文。",
        "",
        f"## 核心论文推荐（Top 5）",
    ]
    for i, p in enumerate(ranked[:5], 1):
        lines.append(
            f"{i}. **{p.get('title','')}** [{p.get('year','')}] "
            f"— 引用 {p.get('citation_count',0)} — 相关性 {p.get('relevance_score',0):.1f}/10"
        )
    lines += [
        "",
        "## 检索说明",
        "由于 LLM 不可用，本次未生成完整综述，仅返回论文列表与基础元信息。",
    ]
    return "\n".join(lines)


async def synthesize_node(state: SearchState) -> SearchState:
    """生成结构化 Markdown 综述报告。"""

    ranked = (state.get("ranked_papers") or [])[:20]
    query = state["original_query"]

    if not ranked:
        return {**state, "report": "未检索到相关论文。", "status": "building_graph"}

    papers_text = "\n\n".join([
        f"**[Paper {i+1}]** {p.get('title','')}\n"
        f"Year: {p.get('year','')} | Citations: {p.get('citation_count',0)} | Venue: {p.get('venue','')}\n"
        f"Relevance: {p.get('relevance_score',0):.1f}/10 | URL: {p.get('url','')}\n"
        f"Abstract: {p.get('abstract','')[:400]}"
        for i, p in enumerate(ranked)
    ])
    # ===== 纵深防御 (VULN-001 Layer 1) =====
    # 论文元数据来自外部 API (Semantic Scholar / OpenAlex)，
    # title/abstract 字段可被恶意构造，wrap_user_input 用 XML 标签隔离。
    safe_papers = wrap_user_input(papers_text, tag="paper_list")

    prompt = f"""根据以下学术论文列表，为研究问题生成一份结构化文献综述报告。

研究问题：{query}

检索论文列表：
{safe_papers}

请生成Markdown格式的综述报告，严格包含以下6个部分：

## 研究概述
（2-3句话：该领域的研究现状和主要挑战）

## 核心论文推荐（Top 5）
（每篇：论文名+年份+核心贡献+推荐理由，格式：**论文名** [年份]）

## 研究方向分类
（按研究方法/应用场景/理论基础等分2-4类，每类列出2-4篇论文及一句话说明）

## 关键研究趋势
（列出3个近年重要趋势，每个趋势2-3句话说明）

## 延伸阅读
（简短列表，格式：- [论文名](URL) — 一句话说明）

## 检索说明
（本次检索：数据源、检索轮次、总论文数、评分方法说明）

要求：分析要有实质内容，不要只列清单；中文为主，论文名保持英文。"""

    report, usage = await call_llm(
        prompt,
        task_type="synthesis",
        system=SYSTEM + isolation_system_suffix(),
        max_tokens=3500,
        provider=state.get("provider"),
    )

    # 兜底：LLM 失败时返回极简报告
    if not report or not report.strip():
        report = _fallback_report(query, ranked)

    # ===== 纵深防御 (VULN-001 Layer 1) =====
    # 检测 LLM 输出中是否含可疑 HTML 标签 / 事件处理器 / 伪协议，
    # 若有则降级到模板报告（不污染前端 DOM）。
    #
    # 历史 (H7): 旧 denylist 只匹配 `onerror=` 这种紧凑形式，
    # 无法拦截 SVG SMIL 事件 / 空白混淆 / HTML 实体绕过。常见绕过的例子：
    #   * `<svg><animate onbegin=alert(1)></svg>` —— SVG SMIL 事件
    #   * `onerror =alert(1)` —— onerror 后面有空白再 `=`
    #   * `<a href="java&#x09;script:alert(1)">` —— tab/换行混淆 javascript:
    #   * `<style>body{...}` / `<form>` / `<input>` / `<link>` / `<meta>` —— 危险 HTML
    #   * `data:text/html,<script>alert(1)</script>` —— data URI
    DANGEROUS_PATTERNS = [
        "<script", "javascript:", "vbscript:",
        "<iframe", "<object", "<embed", "<svg", "<math",
        "<form", "<input", "<style", "<link", "<meta", "<base",
        "data:text/html",
    ]
    # 用正则匹配带可选空白的事件处理器属性（`onerror=`、`onerror =`、
    # `onerror  =`、`onerror\t=`、`onerror\n=`）。匹配 `on\w+` 之后 0+
    # 个空白再 `=`。这对 SVG SMIL (`onbegin`、`onrepeat`、`onload`) 和
    # HTML 内联事件 (`onclick`、`onerror`、`onmouseover` 等) 都生效。
    on_attr_re = re.compile(r"on[a-z]+\s*=", re.IGNORECASE)

    # 关键：先做 HTML 实体解码（`java&#x09;script:` → `java\tscript:`），
    # 再做大小写归一化，再做 denylist 匹配。否则实体混淆的伪协议
    # （如 `java&#x09;script:`）会绕过 `javascript:` 子串检查。
    decoded = html.unescape(report).lower()
    # 把所有空白折叠成单个空格（应对 `java&#x09;script:` → `java\tscript:`
    # 这种带空白伪协议）。
    whitespace_folded = re.sub(r"\s+", " ", decoded)
    # `javascript:` / `vbscript:` 在浏览器里允许带任意空白 — 用正则匹配
    # `java\s*script:` 和 `vb\s*script:` 覆盖所有混淆形式。
    pseudo_proto_re = re.compile(r"(?:java|vb)\s*script\s*:", re.IGNORECASE)
    if (
        any(p in whitespace_folded for p in DANGEROUS_PATTERNS)
        or pseudo_proto_re.search(whitespace_folded)
        or on_attr_re.search(decoded)
    ):
        report = _fallback_report(query, ranked)

    cost_update = merge_usage_into_state(state, usage)

    return {
        **state,
        **cost_update,
        "report": report,
        "status": "building_graph",
    }
