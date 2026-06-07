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
}

export function ReportPanel({
  report, loading, query,
  errorMsg = null, lastQuery = null, onRetry,
}: Props) {
  const [copied, setCopied] = useState(false);

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
    // 延迟撤销: a.click() 触发下载是异步的, 立即撤销会导致 Firefox/Safari 下载失败
    setTimeout(() => URL.revokeObjectURL(url), 100);
  };

  return (
    <main className="flex-1 bg-slate-50 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-baseline gap-2">
            <h2 className="text-sm font-semibold text-slate-600">研究报告</h2>
            {query && <span className="text-xs text-slate-400">— {query}</span>}
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
            </div>
          )}
        </div>

        {loading && (
          <div className="bg-white border border-slate-200 rounded-lg p-6 text-center text-slate-500">
            <div className="inline-block animate-spin w-5 h-5 border-2 border-brand-500 border-t-transparent rounded-full mb-2" />
            <p className="text-sm">正在驱动 8 节点流水线检索中...</p>
            <p className="text-xs text-slate-400 mt-1">查询分解 → 双源检索 → 引文扩展 → 三维排序 → 综述生成</p>
          </div>
        )}

        {!loading && !report && !errorMsg && (
          <div className="bg-white border border-dashed border-slate-300 rounded-lg p-12 text-center">
            <p className="text-slate-500 text-sm">左侧输入研究问题并点击「搜索」开始</p>
            <p className="text-slate-400 text-xs mt-2">
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
            className="report-body bg-white border border-slate-200 rounded-lg p-6 shadow-sm"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        )}
      </div>
    </main>
  );
}
