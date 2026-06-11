import { useMemo, useState } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

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
}

export function ReportPanel({
  report, loading, query,
  errorMsg = null, lastQuery = null, onRetry,
  bibtex = '', ris = '',
}: Props) {
  const [copied, setCopied] = useState(false);
  const [exportedFormat, setExportedFormat] = useState<string | null>(null);

  const html = useMemo(() => {
    if (!report) return '';
    try {
      // 三层 XSS 防护链：marked → DOMPurify 白名单 → React 渲染
      // 关键：DOMPurify.sanitize() 必须在 dangerouslySetInnerHTML 之前调用，
      // 防止 LLM 输出 <script> / onerror= 等可执行 payload。
      const rawHtml = marked.parse(report) as string;
      const sanitized = DOMPurify.sanitize(rawHtml, {
        ALLOWED_TAGS: [
          'h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'li',
          'strong', 'em', 'a', 'code', 'pre', 'blockquote',
          'br', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'hr',
        ],
        ALLOWED_ATTR: ['href', 'target', 'rel'],
        FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'input', 'object', 'embed'],
        FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'style'],
      });
      // R9 阶段 3 (审计员 #3): tabnabbing 防护
      // 之前 marked 渲染 LLM 输出的 Markdown 链接带 [text](url){:target="_blank"} 时
      // 会生成 <a target=_blank> 但没强制 rel=noopener, 新窗口可通过 window.opener
      // 反向操控父页 (XSS 等级 low, 但报告里外部链接可点, 防御纵深必须有).
      // 保守方案: ALLOWED_ATTR 保留 target (让用户能新窗口打开), sanitize 后用
      // DOMParser 兜底遍历所有 target=_blank 的 <a>, 显式补 rel="noopener noreferrer".
      // 不激进 (即不在 ALLOWED_ATTR 里删 target), 因为论文链接在原页面打开会丢失报告.
      if (typeof DOMParser !== 'undefined' && /target=["']_blank["']/i.test(sanitized)) {
        const doc = new DOMParser().parseFromString(sanitized, 'text/html');
        doc.querySelectorAll('a[target="_blank"]').forEach((a) => {
          a.setAttribute('rel', 'noopener noreferrer');
        });
        return doc.body.innerHTML;
      }
      return sanitized;
    } catch (e) {
      // 兜底：parse 失败时转义所有 < > 字符
      return DOMPurify.sanitize(report.replace(/</g, '&lt;').replace(/>/g, '&gt;'));
    }
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

  // R10.5 P0: BibTeX / RIS 下载, 一键导入 Zotero / Mendeley / EndNote
  const handleExport = (format: 'bibtex' | 'ris') => {
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
            <div className="flex gap-0 shrink-0">
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
              <button
                onClick={handleDownload}
                className="font-mono text-[10px] uppercase tracking-[0.12em] px-2.5 py-1 transition-colors border-r"
                style={{
                  color: 'var(--sf-muted)',
                  borderColor: 'var(--sf-border)',
                }}
                title="下载 Markdown 报告"
              >
                Download
              </button>
              {hasExport && (
                <>
                  <button
                    onClick={() => handleExport('bibtex')}
                    className="font-mono text-[10px] uppercase tracking-[0.12em] px-2.5 py-1 transition-colors border-r"
                    style={{
                      color: exportedFormat === 'bibtex' ? 'var(--sf-accent)' : 'var(--sf-muted)',
                      borderColor: 'var(--sf-border)',
                    }}
                    title="导出 BibTeX (导入 Zotero / JabRef)"
                  >
                    {exportedFormat === 'bibtex' ? '✓ .bib' : '.bib'}
                  </button>
                  <button
                    onClick={() => handleExport('ris')}
                    className="font-mono text-[10px] uppercase tracking-[0.12em] px-2.5 py-1 transition-colors"
                    style={{
                      color: exportedFormat === 'ris' ? 'var(--sf-accent)' : 'var(--sf-muted)',
                    }}
                    title="导出 RIS (导入 EndNote / Mendeley)"
                  >
                    {exportedFormat === 'ris' ? '✓ .ris' : '.ris'}
                  </button>
                </>
              )}
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

        {/* M-19 (R10.5) UI 差异化: 综述末尾的"原始文献来源"表格提示.
            Editorial 风格: 细线分隔 + mono 文字 + 缩进引用感. */}
        {!loading && report && html.includes('原始文献来源') && (
          <div
            className="mt-8 pt-4 border-t flex items-start gap-3 text-[11px] font-ui"
            data-testid="paper-anchors-different"
            style={{ borderColor: 'var(--sf-border)' }}
            title="其他工具 (知网/Google Scholar/Semantic Scholar) 都不生成可核查的原始文献来源表"
          >
            <span
              className="font-mono text-base leading-none"
              style={{ color: 'var(--sf-accent)' }}
            >
              ¶
            </span>
            <span style={{ color: 'var(--sf-muted)' }}>
              <span className="font-semibold" style={{ color: 'var(--sf-accent)' }}>
                原始文献来源表
              </span>{' '}
              已附在综述末尾 (含 SS ID + 直链),
              您可逐条点开核对综述里诸如「某论文 2017 年提出 Transformer」之类的声明。
            </span>
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
