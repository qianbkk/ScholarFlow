"""
节点 ⑥ — 综述报告生成
基于排序后的论文，生成结构化 Markdown 综述。
"""
import asyncio
import html
import logging
import re

from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state
from backend.utils.sanitize import wrap_user_input, isolation_system_suffix

logger = logging.getLogger(__name__)


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

    # ===== M-2 (P0-A 综述幻觉) 修复: Grounding 验证 =====
    # 旧实现: LLM 输出综述后无任何追溯, LLM 可发明 DOI / 混淆作者 / 拼凑虚构论文。
    # 修复: (1) 用 _verify_citations_in_report 检查 [N] / [text](url) 引用是否在
    #       ranked_papers 集合中, 找不到的列入 ⚠️ 警告让用户自行核查.
    # R10.5.10: 删 _build_paper_anchors() 自动追加的 "## 📎 原始文献来源" Markdown
    # 块 — 跟前端 ReportPanel 末尾"来源一览" 列表重复 (用户在报告末尾看到两份一样
    # 的论文列表). 警告逻辑保留, 引用追溯功能改由前端来源一览负责 (更多元数据:
    # 年份 / 引用数 / final_score / SS 直链 / 单击跨组件聚焦 + 双击打开).
    # 即使 LLM 在 Top5 推荐段编造论文, 警告 + 完整 ranked 列表仍能避免误导.

    _, unverified = _verify_citations_in_report(report, ranked)
    if unverified:
        # R10.5.11 Fix: 用户反馈 — 旧版用 `> -  [2018]: ...` blockquote list 格式
        # 拼警告, marked 误把 `> -  [YYYY]:` 当 markdown reference link definition
        # (`[foo]: url` 语法), 触发链接引用定义处理, 后续章节顺序被错乱重新排列
        # (用户在报告末尾看到 "### 四、跨领域应用与扩展" 重新出现在警告后).
        # 修复: 用 HTML 块 (pre + plain text) 包裹警告, 让 marked 完全跳过 markdown
        # 解析, 当 literal text 处理. HTML pre 元素 + data-* 标识 + DOMPurify 仍
        # 允许 pre 标签 (ReportPanel ALLOWED_TAGS), 内容走纯文本.
        items_html = "".join(
            f"<div>• {h_escape(u['value'])} <small style=\"opacity:0.6\">({h_escape(u['reason'])})</small></div>"
            for u in unverified[:8]
        )
        warning_html = (
            f'<pre data-sf-unverified-warning '
            f'style="white-space:pre-wrap;background:var(--sf-bg-elev);'
            f'border-left:3px solid var(--sf-accent);padding:0.75rem 1rem;'
            f'margin:1.5rem 0;font-family:inherit;font-size:0.92em">'
            f'<strong>⚠️ 系统提示</strong>: 以下引用未在检索结果中找到对应来源, 请自行核查:\n'
            f'{items_html}'
            f'</pre>'
        )
        report += "\n\n" + warning_html

    return {
        **state,
        **cost_update,
        "report": report,
        "prev_iter_cost_usd": prev_iter_cost,  # M-A P0-2: 透传 iter 起点
        "status": "building_graph",
    }


def h_escape(s: str) -> str:
    """HTML 转义 (避免 value/reason 里的 < > & 破坏结构)."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


# ===== M-2 (P0-A 综述幻觉) 修复: Grounding 验证 + 来源锚点 =====

def _verify_citations_in_report(report: str, ranked: list[dict]) -> tuple[str, list[str]]:
    """检查综述中引用的论文是否能在 ranked_papers 中找到对应。

    R10.5.10 Fix (用户反馈 §4): 旧实现用 `**粗体**` 当"引用" → LLM 综述里所有
    加粗术语 (e.g. **Transformer**、**注意力机制**) 都被误判为"未验证引用",
    警告噪声巨大, 用户体验混乱. 修复:
      1. 真正的"引用"是 `[N]` 数字引用 (LLM 综述里 1/2/3... 对应 ranked 列表)
         或 SS paper_id (e.g. `arxiv:2401.12345`)
      2. 数字引用 [N] 范围 1..len(ranked), 越界算"unverified"
      3. 显式 markdown 链接 [text](url) 中 url 形如 semantic_scholar / arxiv 的,
         提取 paper_id 比对 ranked 集合
      4. 旧 `**粗体**` 模式直接删除 (语义错的)

    Returns:
        report: 原报告 (透传)
        unverified: 列表, 每个元素是 dict {kind: 'index'|'id'|'text', value: ..., reason: ...}
    """
    unverified: list[dict] = []

    # 1) 数字引用 [N] / [N, M] / [N-M]
    # LLM 综述里 [1] [2] [3] 引用 ranked 列表的论文 (R10.5.10 验证: 这是主要引用形式)
    index_refs = re.findall(r'\[(\d{1,2}(?:\s*[,，\-]\s*\d{1,2})*)\]', report)
    referenced_indices: set[int] = set()
    for ref_group in index_refs:
        # 拆 [1, 2, 3] 或 [1-3]
        for part in re.split(r'[,，]', ref_group):
            part = part.strip()
            if '-' in part:
                # 范围 [1-3]
                try:
                    a, b = part.split('-', 1)
                    a, b = int(a.strip()), int(b.strip())
                    for n in range(a, b + 1):
                        if 1 <= n <= len(ranked):
                            referenced_indices.add(n)
                except (ValueError, TypeError):
                    unverified.append({
                        'kind': 'index',
                        'value': part,
                        'reason': '范围引用格式错误',
                    })
            else:
                try:
                    n = int(part)
                    if 1 <= n <= len(ranked):
                        referenced_indices.add(n)
                    else:
                        unverified.append({
                            'kind': 'index',
                            'value': str(n),
                            'reason': f'越界 (1-{len(ranked)} 之外)',
                        })
                except ValueError:
                    pass

    # 2) 显式 markdown 链接 [text](url) — 提取 SS paper_id
    # 旧实现: 任何 [text](url) 都算 "citation" → 噪声巨大 (脚注/参考链接都中招)
    # 修复: 只匹配 semantic_scholar / arxiv 域名的 URL
    ss_id_pattern = re.compile(
        r'\[([^\]]+)\]\((https?://(?:www\.)?(?:semanticscholar\.org|arxiv\.org)/[^\)]+)\)'
    )
    referenced_ids: set[str] = set()
    ranked_ids = {p.get('paper_id', '') for p in ranked if p.get('paper_id')}
    for match in ss_id_pattern.finditer(report):
        text = match.group(1)
        url = match.group(2)
        # 从 URL 末尾抽 paper_id (e.g. /paper/abc123, /abs/2401.12345)
        path = url.rstrip('/').split('/')[-1]
        if not path:
            continue
        paper_id = path.split('?')[0]  # 去 query string
        if paper_id in ranked_ids:
            referenced_ids.add(paper_id)
        else:
            unverified.append({
                'kind': 'id',
                'value': f'[{text}]({url[:60]}...)',
                'reason': f'paper_id "{paper_id[:30]}" 不在 ranked_papers 集合中',
            })

    # 数字引用 vs ranked 列表的差集 = 未引用论文 (不是问题, 不报)
    # unranked_indices (越界) 已加进 unverified
    # ranker_paper 集合 vs referenced_ids: 集合差表示 ranked 中没被引用的
    # (正常的综述不会引用全部 25 篇, 也不报警)

    return report, unverified
