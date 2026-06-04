import { useMemo, useState } from 'react';
import { marked } from 'marked';

// marked v14+：setOptions 已废弃，改用 marked.use()。
// 多次调用 use() 会合并，所以这里只设一次。
marked.use({ gfm: true, breaks: true });

interface Props {
  report: string;
  loading: boolean;
  query: string;
}

export function ReportPanel({ report, loading, query }: Props) {
  const [copied, setCopied] = useState(false);

  const html = useMemo(() => {
    if (!report) return '';
    try {
      return marked.parse(report) as string;
    } catch (e) {
      return `<pre>${report}</pre>`;
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
    URL.revokeObjectURL(url);
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

        {!loading && !report && (
          <div className="bg-white border border-dashed border-slate-300 rounded-lg p-12 text-center">
            <p className="text-slate-500 text-sm">左侧输入研究问题并点击「搜索」开始</p>
            <p className="text-slate-400 text-xs mt-2">
              ScholarFlow 会自动从 Semantic Scholar + OpenAlex 拉取候选论文，并生成结构化综述。
            </p>
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
