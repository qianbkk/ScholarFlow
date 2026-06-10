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
    <main className="flex-1 bg-[var(--sf-bg)] overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-baseline gap-2">
            <h2 className="text-sm font-semibold text-slate-600">研究报告</h2>
            {query && <span className="text-xs text-themed-muted">— {query}</span>}
          </div>
          {report && !loading && (
            <div className="flex gap-1.5">
              <button
                onClick={handleCopy}
                className="text-xs px-2.5 py-1 border border-slate-300 rounded text-slate-600 hover:bg-slate-50 transition"
                title="复制 Markdown 报告"
              >
                {copied ? '✓ 已复制' : 'Copy'}
              </button>
              <button
                onClick={handleDownload}
                className="text-xs px-2.5 py-1 border border-slate-300 rounded text-slate-600 hover:bg-slate-50 transition"
                title="下载 Markdown 报告"
              >
                Download
              </button>
              {/* R10.5 P0: BibTeX / RIS 导出, 一键导入 Zotero / Mendeley / EndNote */}
              {hasExport && (
                <>
                  <button
                    onClick={() => handleExport('bibtex')}
                    className="text-xs px-2.5 py-1 border border-amber-300 rounded text-amber-700 hover:bg-amber-50 transition"
                    title="导出 BibTeX (导入 Zotero / JabRef)"
                  >
                    {exportedFormat === 'bibtex' ? '✓ .bib' : '.bib'}
                  </button>
                  <button
                    onClick={() => handleExport('ris')}
                    className="text-xs px-2.5 py-1 border border-amber-300 rounded text-amber-700 hover:bg-amber-50 transition"
                    title="导出 RIS (导入 EndNote / Mendeley / RefMan)"
                  >
                    {exportedFormat === 'ris' ? '✓ .ris' : '.ris'}
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        {loading && (
          <div className="bg-[var(--sf-bg)] border border-slate-200 rounded-lg p-6 text-center text-themed-muted">
            <div className="inline-block animate-spin w-5 h-5 border-2 border-brand-500 border-t-transparent rounded-full mb-2" />
            <p className="text-sm">正在驱动 8 节点流水线检索中...</p>
            <p className="text-xs text-themed-muted mt-1">查询分解 → 双源检索 → 引文扩展 → 三维排序 → 综述生成</p>
          </div>
        )}

        {!loading && !report && !errorMsg && (
          <div className="bg-white border border-dashed border-slate-300 rounded-lg p-12 text-center">
            <p className="text-themed-muted text-sm">左侧输入研究问题并点击「搜索」开始</p>
            <p className="text-themed-muted text-xs mt-2">
              ScholarFlow 会自动从 Semantic Scholar + OpenAlex 拉取候选论文，并生成结构化综述。
            </p>
          </div>
        )}

        {/* Round 4 U4: 错误状态显示 + 重试按钮
            此前错误状态仅显示"请稍后重试"文本，无重试按钮，
            用户必须刷新页面才能再次搜索，体验差。
            修复：当 errorMsg 存在时，渲染红色错误块 + 重试按钮。
            优先级：errorMsg > report > 空状态（三者互斥展示）。 */}
        {!loading && !report && errorMsg && (
          <div
            className="bg-red-50 border border-red-200 rounded-md p-4 text-center"
            data-testid="report-error"
          >
            <p className="text-red-700 text-sm mb-3">{errorMsg}</p>
            {(lastQuery || query) && onRetry && (
              <button
                type="button"
                onClick={() => onRetry(lastQuery || query)}
                className="px-4 py-1.5 bg-red-600 text-white text-sm rounded-md hover:bg-red-700 transition"
              >
                重试
              </button>
            )}
          </div>
        )}

        {!loading && report && (
          <article
            className="report-body border border-slate-200 rounded-lg p-6 shadow-sm"
            style={{ backgroundColor: 'var(--sf-bg)', color: 'var(--sf-text)' }}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        )}

        {/* M-19 (R10.5) UI 差异化: 综述末尾的"原始文献来源"表格 — 知网/Google Scholar/SS
            都不生成可核查来源表. 用 amber 突出信号, 让用户在实际使用中
            看到 ScholarFlow 跟其他工具的差别, 而不是从 README 读"为什么用". */}
        {!loading && report && html.includes('原始文献来源') && (
          <div
            className="mt-2 px-3 py-2 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded-md flex items-center gap-2"
            data-testid="paper-anchors-different"
            title="其他工具 (知网/Google Scholar/Semantic Scholar) 都不生成可核查的原始文献来源表"
          >
            <span className="text-base">📎</span>
            <span>
              综述末尾已自动附原始文献来源表 (含 SS ID + 直链),
              用户可逐条点开核对综述里说的"某论文 2017 年提出 Transformer"这类声明.
            </span>
          </div>
        )}
      </div>
    </main>
  );
}
