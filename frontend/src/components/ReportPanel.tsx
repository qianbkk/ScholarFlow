import { useMemo, useState, useEffect, useRef } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import type { Paper } from '../types';
import { InlinePaperCard } from './InlinePaperCard';

// marked v14+：setOptions 已废弃，改用 marked.use()。
// 多次调用 use() 会合并，所以这里只设一次。
marked.use({ gfm: true, breaks: true });

interface Props {
  report: string;
  loading: boolean;
  query: string;
  // Round 4 U4: 错误状态 + 重试
  // App.tsx 若已持有 useSearch 暴露的 error/lastQuery，可作为 prop 传入。
  // 本次 PR 受约束不能改 App.tsx，所以这里设为 optional，
  // 父组件后续接入时只需多传两个 prop + onRetry 即可，无需再改 ReportPanel。
  errorMsg?: string | null;
  lastQuery?: string | null;
  onRetry?: (query: string) => void;
  // R10.5 P0: BibTeX / RIS 字符串 (后端 SearchResponse 返)
  // 用户一键导入 Zotero / Mendeley / EndNote
  bibtex?: string;
  ris?: string;
  // R10.5.5: 跨组件论文聚焦 — 报告内引用表 / 锚点
  selectedPaperId?: string | null;
  onSelectPaper?: (paperId: string | null) => void;
  papers?: Paper[];
}

export function ReportPanel({
  report, loading, query,
  errorMsg = null, lastQuery = null, onRetry,
  bibtex = '', ris = '',
  selectedPaperId = null, onSelectPaper,
  papers = [],
}: Props) {
  const [copied, setCopied] = useState(false);
  const [exportedFormat, setExportedFormat] = useState<string | null>(null);
  // R10.5.11: Download 按钮 popover — 单按钮, 点出 3 选项 (md/bibtex/ris)
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const downloadMenuRef = useRef<HTMLDivElement | null>(null);

  // popover Esc 关闭 + 点外部关闭
  useEffect(() => {
    if (!downloadMenuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDownloadMenuOpen(false);
    };
    const onClickOutside = (e: MouseEvent) => {
      if (downloadMenuRef.current && !downloadMenuRef.current.contains(e.target as Node)) {
        setDownloadMenuOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('mousedown', onClickOutside);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('mousedown', onClickOutside);
    };
  }, [downloadMenuOpen]);

  // R10.5.5: 报告内的 paper_id 锚点 (后端 synthesis 节点会生成 [论文 N] 引用)
  // 给 paper_id 生成 set, 渲染时在 report-body 末尾注入 data-paper-id 锚点
  const paperIdSet = useMemo(() => {
    const s = new Set<string>();
    for (const p of papers) if (p.paper_id) s.add(p.paper_id);
    return s;
  }, [papers]);

  // R10.5.5: 选中论文变化时, 报告正文末尾的 paper_anchors 表对应行高亮 (CSS-only via data attr)
  useEffect(() => {
    const root = document.querySelector('.report-body');
    if (!root) return;
    // 移除旧高亮
    root.querySelectorAll('[data-sf-selected]').forEach((el) =>
      el.removeAttribute('data-sf-selected')
    );
    if (selectedPaperId) {
      root
        .querySelectorAll(`[data-paper-id="${CSS.escape(selectedPaperId)}"]`)
        .forEach((el) => el.setAttribute('data-sf-selected', 'true'));
    }
  }, [selectedPaperId, report]);

  // R10.5.40 (Agent 1): 选中论文对应的 InlinePaperCard 数据. 找不到 paper
  // (e.g. selectedPaperId 已 stale) 时不渲染, 避免空卡.
  const inlineCardPaper = useMemo(() => {
    if (!selectedPaperId) return null;
    const idx = papers.findIndex((p) => p.paper_id === selectedPaperId);
    if (idx < 0) return null;
    return { paper: papers[idx], index: idx + 1 };
  }, [selectedPaperId, papers]);

  const [html, setHtml] = useState('');

  // R10.5.32 (P1-4): marked.parse 异步化. 旧实现 (R10.5.X) 在 useMemo 同步
  // 解析, 50KB+ 报告 (R10.5.30 D4 接本地论文库后典型输出) 阻塞主线程
  // 100-400ms, React StrictMode 双跑 = 200-800ms. 改 useState + useEffect
  // 让 marked v14+ async 模式在 idle 时跑. 同时 generation counter 防
  // 旧报告覆盖新报告 (search 切换 race).
  const htmlGenRef = useRef(0);
  useEffect(() => {
    if (!report) {
      setHtml('');
      return;
    }
    const myGen = ++htmlGenRef.current;
    let cancelled = false;
    // R10.5.32 (P1-4): 调 marked.parse async API (Promise<string>).
    // marked v14+ 默认 sync, async 模式需要 {async: true} 或直接 await.
    // 文档: https://marked.js.org/using_pro#async
    Promise.resolve(marked.parse(report, { async: true }) as Promise<string> | string)
      .then((rawHtml) => {
        if (cancelled || myGen !== htmlGenRef.current) return;
        // R10.5 Fix-P0-XSS: 四层 XSS 防护链 —
        // ① marked 解析 Markdown → ② DOMPurify 白名单过滤 → ③ DOMParser 属性强化 → ④ React 渲染
        // 关键: DOMPurify 必须在 dangerouslySetInnerHTML 之前调用,
        // 防 LLM 输出 <script> / onerror= / javascript: 等可执行 payload.
        const sanitized = DOMPurify.sanitize(rawHtml, {
          ALLOWED_TAGS: [
            'h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'li',
            'strong', 'em', 'a', 'code', 'pre', 'blockquote',
            'br', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'hr',
            'sup', 'sub', // R10.5: 新增上下标支持 (学术论文常用)
          ],
          // R10.5.8 code-review 修复: 允许 'rel' 和 'name' 透传 — LLM 经常生成
          // 内部锚点 <a name="ref-1"> 和 nofollow 等 rel 修饰, 旧版一刀切
          // 全部剥光导致报告内"论文 N" 引用跳转变 plain text.
          // 'class' / 'id' 仍禁 (防 CSS 注入); 'target' 由下方 DOMParser 统一强制.
          ALLOWED_ATTR: ['href', 'title', 'rel', 'name'],
          FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'input', 'object', 'embed', 'textarea', 'select', 'button'],
          FORBID_ATTR: [
            'onerror', 'onload', 'onclick', 'onmouseover', 'onmouseenter', 'onmouseleave',
            'onfocus', 'onblur', 'onchange', 'onsubmit', 'onkeydown', 'onkeyup',
            'style', 'class', 'id', // R10.5 Fix-P0: 禁止内联样式和 id (防 CSS 注入)
          ],
          // R10.5 Fix-P0: 强制 URL 协议白名单, 防 javascript: / data: 伪协议
          ALLOWED_URI_REGEXP: /^(?:(?:(?:https?|mailto|tel):)|\/|#)/i,
        });

        // ③ DOMParser: 区分"锚点"vs"外链"决定是否开新窗
        // R10.5.8 code-review 修复: 旧实现无条件 target=_blank, 报告内
        // "论文 N"内部锚点 + 同源链接也被开新窗 (15+ 标签页). 新实现:
        //   - href 形如 #xxx  (页内锚点) → 同窗跳转
        //   - href 含 name 属性 (LLM 锚点) → 同窗 (目标 id 在本报告)
        //   - href 同源 (/api/...) → 同窗
        //   - 其余 (http(s):// 外链) → 新窗 + noopener noreferrer 防 tabnabbing
        // R10.5.9 落地: 删 typeof DOMParser === 'undefined' 降级分支 —
        // Vite 5 + 现代浏览器 (Chrome 90+/Firefox 88+/Safari 14+) 100% 可用,
        // 该分支是死代码, 删 11 行. 错误兜底走 catch(e) → 完全转义已存在.
        const doc = new DOMParser().parseFromString(sanitized, 'text/html');
        doc.querySelectorAll('a').forEach((a) => {
          const href = a.getAttribute('href') || '';
          // R10.5 Fix-P0: 二次校验 href 协议, 防 DOMPurify 绕过
          if (/^(javascript|data|vbscript|file):/i.test(href)) {
            a.removeAttribute('href');
            a.setAttribute('data-removed', 'unsafe-protocol');
            return;
          }
          // 内部锚点 / 同源链接: 同窗 (不强制 _blank)
          const isInternalAnchor = href.startsWith('#');
          const isRelativeOrApi = href.startsWith('/') || href.startsWith('#');
          if (isInternalAnchor || isRelativeOrApi) {
            // 保留原 href, 不强制 target=_blank
            return;
          }
          // 外链: 新窗 + 防御 tabnabbing (新窗口无法通过 window.opener 操控父页)
          a.setAttribute('target', '_blank');
          a.setAttribute('rel', 'noopener noreferrer');
          // R10.5: 添加隐式安全提示
          a.setAttribute('title', `${a.textContent || '外部链接'} · 将在新窗口打开`);
        });

        if (!cancelled && myGen === htmlGenRef.current) {
          setHtml(doc.body.innerHTML);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        // 兜底: 完全转义
        console.error('[ReportPanel] XSS 处理失败, 降级到纯文本:', e);
        setHtml(DOMPurify.sanitize(report.replace(/</g, '&lt;').replace(/>/g, '&gt;')));
      });
    return () => {
      cancelled = true;
    };
  }, [report]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      // 降级：选中文本
      const ta = document.createElement('textarea');
      ta.value = report;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (_) {}
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([report], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `scholarflow_report_${Date.now()}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 100);
  };

  // R10.5.11: 统一 Download 函数 (从 popover 选项调)
  // 接受 format 参数: 'md' | 'bibtex' | 'ris'
  const handleDownloadFormat = (format: 'md' | 'bibtex' | 'ris') => {
    setDownloadMenuOpen(false);
    if (format === 'md') {
      const blob = new Blob([report], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `scholarflow_report_${Date.now()}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 100);
      return;
    }
    // bibtex / ris
    const content = format === 'bibtex' ? bibtex : ris;
    if (!content) return;
    const mime = format === 'bibtex'
      ? 'application/x-bibtex'
      : 'application/x-research-info-systems';
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `scholarflow_papers.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 100);
    setExportedFormat(format);
    setTimeout(() => setExportedFormat(null), 1500);
  };

  // R10.5 P0: BibTeX/RIS 只有在有论文时才显示, 否则空字符串会下载空文件
  const hasExport = !!(bibtex && bibtex.includes('@article'));

  return (
    // R10.5.4 Editorial: 报告页 = 期刊中央跨页 (max-w-2xl 38rem 黄金阅读宽度).
    // 顶部用一行"栏目标题 + 工具栏", 论文体正文, 底部分隔细线.
    <main
      className="flex-1 overflow-y-auto"
      style={{ backgroundColor: 'var(--sf-bg)' }}
    >
      <div className="max-w-2xl mx-auto px-6 py-8">
        {/* 报头式工具栏 — "§ 3 综述" + 复制/下载/导出 */}
        <div className="mb-6 flex items-end justify-between gap-3 border-b-2 pb-3" style={{ borderColor: 'var(--sf-text)' }}>
          <div className="min-w-0">
            <div className="flex items-baseline gap-2">
              <span
                className="font-mono text-[10px] uppercase tracking-[0.18em]"
                style={{ color: 'var(--sf-accent)' }}
              >
                § 3
              </span>
              <h2
                className="font-display text-xl italic font-semibold leading-tight"
                style={{ color: 'var(--sf-text)' }}
              >
                综述报告
              </h2>
            </div>
            {query && (
              <p
                className="font-body text-[13px] italic mt-1 truncate"
                style={{ color: 'var(--sf-muted)' }}
                title={query}
              >
                — {query}
              </p>
            )}
          </div>
          {report && !loading && (
            <div className="flex gap-0 shrink-0 items-stretch">
              <button
                onClick={handleCopy}
                className="font-mono text-[10px] uppercase tracking-[0.12em] px-2.5 py-1 transition-colors border-r"
                style={{
                  color: copied ? 'var(--sf-accent)' : 'var(--sf-muted)',
                  borderColor: 'var(--sf-border)',
                }}
                title="复制 Markdown 报告"
              >
                {copied ? '✓ Copied' : 'Copy'}
              </button>
              {/* R10.5.11: Download 按钮合 1, popover 选 3 格式 */}
              <div className="relative" ref={downloadMenuRef}>
                <button
                  onClick={() => setDownloadMenuOpen((s) => !s)}
                  aria-haspopup="menu"
                  aria-expanded={downloadMenuOpen}
                  className="font-mono text-[10px] uppercase tracking-[0.12em] px-2.5 py-1 transition-colors"
                  style={{
                    color: downloadMenuOpen ? 'var(--sf-accent)' : 'var(--sf-muted)',
                    borderColor: 'var(--sf-border)',
                  }}
                  title="下载 (Markdown / BibTeX / RIS)"
                >
                  Download ▾
                </button>
                {downloadMenuOpen && (
                  <div
                    role="menu"
                    data-testid="download-menu"
                    className="absolute right-0 top-full mt-1 z-20 font-mono text-[11px]"
                    style={{
                      backgroundColor: 'var(--sf-bg)',
                      border: '1px solid var(--sf-border)',
                      boxShadow: '0 4px 14px rgba(0,0,0,0.10)',
                      minWidth: '180px',
                    }}
                  >
                    <button
                      role="menuitem"
                      onClick={() => handleDownloadFormat('md')}
                      className="w-full text-left px-3 py-1.5 transition-colors flex items-center justify-between gap-3"
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--sf-bg-elev)')}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                      style={{ color: 'var(--sf-text)' }}
                    >
                      <span className="uppercase tracking-[0.1em]">Markdown</span>
                      <span style={{ color: 'var(--sf-muted)' }}>.md</span>
                    </button>
                    {hasExport && (
                      <>
                        <div className="border-t" style={{ borderColor: 'var(--sf-border)' }} />
                        <button
                          role="menuitem"
                          onClick={() => handleDownloadFormat('bibtex')}
                          className="w-full text-left px-3 py-1.5 transition-colors flex items-center justify-between gap-3"
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--sf-bg-elev)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                          style={{ color: 'var(--sf-text)' }}
                        >
                          <span className="uppercase tracking-[0.1em]">BibTeX</span>
                          <span style={{ color: 'var(--sf-muted)' }}>.bib</span>
                        </button>
                        <button
                          role="menuitem"
                          onClick={() => handleDownloadFormat('ris')}
                          className="w-full text-left px-3 py-1.5 transition-colors flex items-center justify-between gap-3"
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--sf-bg-elev)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                          style={{ color: 'var(--sf-text)' }}
                        >
                          <span className="uppercase tracking-[0.1em]">RIS</span>
                          <span style={{ color: 'var(--sf-muted)' }}>.ris</span>
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {loading && (
          <div
            className="text-center py-16"
            style={{ color: 'var(--sf-muted)' }}
          >
            <div
              className="inline-block w-6 h-6 border-2 border-t-transparent rounded-full mb-4 animate-spin"
              style={{ borderColor: 'var(--sf-accent)', borderTopColor: 'transparent' }}
            />
            <p
              className="font-display italic text-base"
              style={{ color: 'var(--sf-text)' }}
            >
              正在生成综述…
            </p>
            <p
              className="font-mono text-[10px] uppercase tracking-[0.18em] mt-2"
              style={{ color: 'var(--sf-muted)' }}
            >
              查询分解 → 双源检索 → 引文扩展 → 三维排序 → 综述生成
            </p>
          </div>
        )}

        {!loading && !report && !errorMsg && (
          <div
            className="py-20 text-center border-y"
            style={{ borderColor: 'var(--sf-border)' }}
          >
            <p
              className="font-display italic text-2xl"
              style={{ color: 'var(--sf-text)' }}
            >
              静候您的研究问题
            </p>
            <p
              className="font-body text-sm mt-3 max-w-md mx-auto leading-relaxed"
              style={{ color: 'var(--sf-muted)' }}
            >
              在左侧输入问题并按 <span className="font-mono text-xs px-1.5 py-0.5" style={{ backgroundColor: 'var(--sf-bg-elev)' }}>检索</span> 开始。
              ScholarFlow 会自动从 Semantic Scholar + OpenAlex 拉取候选论文,
              并由 LLM 编织成结构化综述。
            </p>
          </div>
        )}

        {/* Round 4 U4: 错误状态显示 + 重试按钮 */}
        {!loading && !report && errorMsg && (
          <div
            className="py-12 text-center"
            data-testid="report-error"
          >
            <p
              className="font-display italic text-lg"
              style={{ color: 'var(--sf-accent)' }}
            >
              {errorMsg}
            </p>
            {(lastQuery || query) && onRetry && (
              <button
                type="button"
                onClick={() => onRetry(lastQuery || query)}
                className="mt-5 px-5 py-2 text-sm font-display italic font-semibold transition-colors"
                style={{
                  backgroundColor: 'var(--sf-accent)',
                  color: 'var(--sf-bg)',
                }}
              >
                重试 →
              </button>
            )}
          </div>
        )}

        {!loading && report && (
          <article
            className="report-body"
            style={{ color: 'var(--sf-text)' }}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        )}

        {/* R10.5.10: 删"原始文献来源表"提示 banner + 来源一览全显.
            旧实现: 后端 synthesis_agent 在 report 末尾追加 "## 📎 原始文献来源（可核查）"
            Markdown 块, 前端又加 "原始文献来源表" 提示, 再加 "来源一览 (12)" 截断列表
            — 三处重复, 用户看到两份一样的论文列表. 修复:
            1. 后端删 _build_paper_anchors() (注释保留追溯)
            2. 前端删 "原始文献来源表" 提示 banner
            3. 来源一览不再截断 12, 全显 (ranker 评 25 篇, 不再藏)
            4. 提示信息移到标题 subline, 一行说清作用 */}
        {/* R10.5.40 (Agent 1): InlinePaperCard — 用户点击引用 / 来源一览中某篇
            论文时, 在报告流中展开内嵌卡片. 一次一张, Esc 或 × 关闭. 选中时
            selectedPaperId === paper.paper_id, 用 onSelectPaper(null) 关闭. */}
        {!loading && report && inlineCardPaper && onSelectPaper && (
          <InlinePaperCard
            paper={inlineCardPaper.paper}
            index={inlineCardPaper.index}
            onClose={() => onSelectPaper(null)}
          />
        )}
        {!loading && report && papers.length > 0 && onSelectPaper && (
          <div
            className="mt-8 pt-4 border-t"
            style={{ borderColor: 'var(--sf-border)' }}
          >
            <div className="flex items-baseline gap-2 mb-1">
              <span
                className="font-mono text-[10px] uppercase tracking-[0.18em]"
                style={{ color: 'var(--sf-accent)' }}
              >
                § 引文
              </span>
              <h3
                className="font-display italic text-sm font-semibold"
                style={{ color: 'var(--sf-text)' }}
              >
                来源一览 ({papers.length})
              </h3>
            </div>
            <p
              className="text-[10px] font-mono uppercase tracking-wider mb-3"
              style={{ color: 'var(--sf-muted)' }}
            >
              单击 = 跨组件聚焦 · 双击 / Ctrl+单击 = 打开论文
            </p>
            <ol className="space-y-1.5">
              {papers.map((p, i) => {
                const isSelected = p.paper_id && p.paper_id === selectedPaperId;
                return (
                  <li
                    key={p.paper_id || i}
                    data-paper-id={p.paper_id}
                    data-sf-selected={isSelected ? 'true' : undefined}
                    onClick={(e) => {
                      const wantsOpen = e.ctrlKey || e.metaKey || e.detail > 1;
                      if (wantsOpen) {
                        if (p.url && /^https?:\/\//i.test(p.url)) {
                          window.open(p.url, '_blank', 'noopener,noreferrer');
                        }
                        return;
                      }
                      if (p.paper_id) onSelectPaper(isSelected ? null : p.paper_id);
                    }}
                    className="flex items-baseline gap-3 py-1 cursor-pointer transition-colors"
                    style={{
                      color: 'var(--sf-text)',
                      paddingLeft: '10px',
                      borderLeft: isSelected
                        ? '3px solid var(--sf-accent)'
                        : '3px solid transparent',
                    }}
                    title={`${p.title}\n单击 = 跨组件聚焦 · 双击 / Ctrl+单击 = 打开论文`}
                  >
                    <span
                      className="font-display italic text-sm shrink-0 w-5 text-right tabular-nums"
                      style={{ color: 'var(--sf-accent)' }}
                    >
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <span
                      className="font-body text-[13px] flex-1 min-w-0 truncate"
                      style={{ color: 'var(--sf-text)' }}
                    >
                      {p.title}
                    </span>
                    <span
                      className="font-mono text-[10px] uppercase tracking-wider tabular-nums shrink-0"
                      style={{ color: 'var(--sf-muted)' }}
                    >
                      {p.year || '—'} · ★{p.final_score.toFixed(1)}
                    </span>
                  </li>
                );
              })}
            </ol>
          </div>
        )}

        {/* 期刊页脚 — 极小 mono 标记, 假装 "本文完" */}
        {!loading && report && (
          <div
            className="mt-12 pt-4 text-center font-mono text-[9px] uppercase tracking-[0.3em]"
            style={{ color: 'var(--sf-muted)' }}
          >
            ❦ &nbsp; 本文完 &nbsp; ❦
          </div>
        )}
      </div>
    </main>
  );
}
