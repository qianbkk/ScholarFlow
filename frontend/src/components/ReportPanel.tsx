import { useMemo } from 'react';
import { marked } from 'marked';

interface Props {
  report: string;
  loading: boolean;
  query: string;
}

export function ReportPanel({ report, loading, query }: Props) {
  const html = useMemo(() => {
    if (!report) return '';
    try {
      // 设置 GFM 风格
      marked.setOptions({ gfm: true, breaks: true });
      return marked.parse(report) as string;
    } catch (e) {
      return `<pre>${report}</pre>`;
    }
  }, [report]);

  return (
    <main className="flex-1 bg-slate-50 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6">
        <div className="mb-3 flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-slate-600">研究报告</h2>
          {query && <span className="text-xs text-slate-400">— {query}</span>}
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
