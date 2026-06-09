"""
节点 ⑥ — 综述报告生成
基于排序后的论文，生成结构化 Markdown 综述。
"""
import asyncio
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


async def synthesize_node(state: SearchState, services=None) -> SearchState:
    """生成结构化 Markdown 综述报告.

    R10.5 P1-1: 加 services 可选参数 (P1-1 渐进式依赖注入).
      - services=None: 用本模块 call_llm (旧测试 patch 仍生效)
      - services=NodeServices(llm=MockLLM(...)): 测试可注入替身
    """
    # 解析 LLM client (向后兼容)
    if services is not None and services.llm is not None:
        llm_client = services.llm
    else:
        # 默认: 本模块级 call_llm 引用. 这跟旧行为完全一致,
        # 也让 patch.object(synthesis_agent, "call_llm", mock) 仍能拦截.
        llm_client = call_llm

    # M-A 修复 (P0-2 PER_ITER 语义): 入口透传 prev_iter_cost_usd。
    # synthesize 是 router 决定"不再 refine"后的终态节点, 此时 prev_iter_cost_usd
    # 不再被 router 读, 但保留入口透传以保证 state 字段一致性, 方便 cost_tracker
    # 和外部审计回看"最后一 iter 起点成本"。
    prev_iter_cost = state.get("total_cost_usd", 0.0) or 0.0

    # FIX: 统一 ranked 论文数为 15 — 与 ranker_agent / graph_builder 对齐
    # Round 5 S-1: 从 25 → 15, 减少 LLM input token 浪费 (~40% 截断量)。
    # 旧 [:20] 丢掉了 ranker 评出的 21-25 名论文（暗物质）。
    ranked = (state.get("ranked_papers") or [])[:15]
    query = state["original_query"]

    if not ranked:
        return {
            **state,
            "report": "未检索到相关论文。",
            "prev_iter_cost_usd": prev_iter_cost,  # M-A P0-2: 透传
            "status": "building_graph",
        }

    papers_text = "\n\n".join([
        f"**[Paper {i+1}]** {p.get('title','')}\n"
        f"Year: {p.get('year','')} | Citations: {p.get('citation_count',0)} | Venue: {p.get('venue','')}\n"
        f"Relevance: {p.get('relevance_score',0):.1f}/10 | URL: {p.get('url','')}\n"
        f"Abstract: {p.get('abstract','')[:200]}"
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

    report, usage = await asyncio.wait_for(
        llm_client(
            prompt,
            task_type="synthesis",
            system=SYSTEM + isolation_system_suffix(),
            max_tokens=3500,
            provider=state.get("provider"),
        ),
        timeout=90.0,  # R10.5 Fix-P: 节点级 90s 上限.  synthesis 是单次 LLM
                       # 调用里最重的 (max_tokens=3500), 用户实测 30-60s, 90s 留 1.5x buffer.
                       # 超过走 _fallback_report 兜底, 不再让节点占满整个 480s endpoint timeout.
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
    # R10.5 Fix-M (审计 PPP §4.2): 后端 XSS 检测改 warning-only.
    # 旧逻辑触发 → _fallback_report → 用户看到质量极低报告却不知道原因.
    # 前端 DOMPurify (FORBID_TAGS/FORBID_ATTR 白名单) 是唯一可信 XSS 防线,
    # 后端检测的误报是 false positive 风险. 改为 logger.warning, 不替换报告.
    if (
        any(p in whitespace_folded for p in DANGEROUS_PATTERNS)
        or pseudo_proto_re.search(whitespace_folded)
        or on_attr_re.search(decoded)
    ):
        logger.warning(
            f"[synthesis] LLM output contains potential XSS markers; "
            f"keeping report (DOMPurify will sanitize on frontend). "
            f"query={query[:60]!r}"
        )

    cost_update = merge_usage_into_state(state, usage)

    # ===== M-2 (P0-A 综述幻觉) 修复: Grounding 验证 + 来源锚点 =====
    # 旧实现: LLM 输出综述后无任何追溯, LLM 可发明 DOI / 混淆作者 / 拼凑虚构论文。
    # 修复: (1) 在综述末尾追加可点击的原始来源锚点表 (paper_id + URL),
    #       (2) 用 _verify_citations_in_report 检查 **粗体标题** 是否能在 ranked_papers 中
    #           找到对应; 找不到的列入 ⚠️ 警告, 让用户自行核查。
    # 即使 LLM 在 Top5 推荐段编造论文, 用户能看到警告 + 完整 ranked 列表, 避免被误导。
    paper_anchors = _build_paper_anchors(ranked)
    report = (report or "") + paper_anchors

    _, unverified = _verify_citations_in_report(report, ranked)
    if unverified:
        warning = (
            "\n\n> ⚠️ **系统提示**: 以下引用未在检索结果中找到对应来源, 请自行核查:\n"
            + "\n".join(f"> - {t}" for t in unverified[:5])
        )
        report += warning

    return {
        **state,
        **cost_update,
        "report": report,
        "prev_iter_cost_usd": prev_iter_cost,  # M-A P0-2: 透传 iter 起点
        "status": "building_graph",
    }


# ===== M-2 (P0-A 综述幻觉) 修复: Grounding 验证 + 来源锚点 =====

def _verify_citations_in_report(report: str, ranked: list[dict]) -> tuple[str, list[str]]:
    """检查综述中 **粗体标题** 是否对应到 ranked_papers。

    R10.5 Fix-K (审计 PPP §4.3 / QQQ §3.3): 旧 Jaccard 阈值 0.5 + len(cited_words)
    分母, 容易误匹配 (e.g. "A Survey of LLM" vs "A Comprehensive Survey on
    LLM" 共享 4/5=80% 词被误判为同一论文). 修复:
      1. 先精确子串包含 (忽略大小写)
      2. 模糊 Jaccard 阈值 0.5 → 0.7
      3. 分母 max(len_cited, len_t) 而非 len_cited — 防止短 cited 高通过率
    """
    ranked_titles = [p.get("title", "").lower() for p in ranked if p.get("title")]
    cited_in_report = re.findall(r'\*\*([^*]{5,80})\*\*', report)
    unverified = []
    for cited in cited_in_report:
        cited_lower = cited.lower()
        cited_words = set(cited_lower.split())
        matched = False
        for t in ranked_titles:
            t_words = set(t.split())
            # Stage 1: 精确子串包含 (任一方向)
            if cited_lower in t or t in cited_lower:
                matched = True
                break
            # Stage 2: 模糊 Jaccard, 分母用 max 长度
            intersection = len(cited_words & t_words)
            if intersection / max(len(cited_words), len(t_words), 1) > 0.7:
                matched = True
                break
        if not matched and len(cited) > 10:
            unverified.append(cited)
    return report, unverified


def _build_paper_anchors(ranked: list[dict]) -> str:
    """在综述末尾生成可点击的原始来源锚点表。

    格式:
      ## 📎 原始文献来源（可核查）
      1. [Title 1](url) — SS ID: `xxx`
      ...
    """
    if not ranked:
        return ""
    lines = ["\n\n---\n## 📎 原始文献来源（可核查）\n"]
    for i, p in enumerate(ranked[:15], 1):
        ss_id = p.get("paper_id", "unknown")
        url = p.get("url", f"https://semanticscholar.org/paper/{ss_id}")
        title = (p.get("title") or "Unknown").strip()
        lines.append(f"{i}. [{title}]({url}) — SS ID: `{ss_id}`")
    return "\n".join(lines)
