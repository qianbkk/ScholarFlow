import { useState } from 'react';
import type { Paper } from '../types';

interface Props {
  loading: boolean;
  onSearch: (query: string, budget: number, maxIter: number) => void;
  onReset: () => void;
  papers: Paper[];
  lastQuery: string;
}

const SUGGESTIONS = [
  'transformer attention mechanism',
  '大语言模型在代码生成中的应用',
  'multi-agent reinforcement learning coordination',
  'retrieval augmented generation survey',
  'chain of thought reasoning in LLMs',
];

export function QueryPanel({ loading, onSearch, onReset, papers, lastQuery }: Props) {
  const [query, setQuery] = useState('');
  const [budget, setBudget] = useState(2.0);
  const [maxIter, setMaxIter] = useState(3);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    onSearch(query, budget, maxIter);
  };

  const useSuggestion = (s: string) => {
    setQuery(s);
  };

  const handleReset = () => {
    setQuery("");
    setBudget(2.0);
    setMaxIter(3);
    onReset();
  };

  return (
    <aside className="w-1/4 min-w-[280px] bg-white border-r border-slate-200 flex flex-col h-full">
      <div className="p-3 border-b border-slate-100">
        <h2 className="text-sm font-semibold text-slate-700 mb-2">研究查询</h2>
        <form onSubmit={submit} className="space-y-2">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入研究问题（中英文均可）..."
            rows={2}
            className="w-full text-sm border border-slate-300 rounded-md p-2 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent resize-none"
          />

          <div className="flex items-center gap-2 text-xs">
            <label className="flex items-center gap-1 text-slate-600">
              预算
              <input
                type="number"
                min={0.1}
                max={20}
                step={0.1}
                value={budget}
                onChange={(e) => setBudget(parseFloat(e.target.value) || 2.0)}
                className="w-14 border border-slate-300 rounded px-1.5 py-0.5 text-center"
              />
            </label>
            <label className="flex items-center gap-1 text-slate-600">
              迭代
              <input
                type="number"
                min={1}
                max={5}
                value={maxIter}
                onChange={(e) => setMaxIter(parseInt(e.target.value) || 3)}
                className="w-12 border border-slate-300 rounded px-1.5 py-0.5 text-center"
              />
            </label>
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="ml-auto flex-1 bg-brand-600 hover:bg-brand-700 disabled:bg-slate-300 text-white text-sm font-medium py-1.5 rounded-md transition"
            >
              {loading ? '搜索中...' : '搜索'}
            </button>
            <button
              type="button"
              onClick={handleReset}
              className="px-2.5 py-1.5 text-sm border border-slate-300 rounded-md hover:bg-slate-50"
            >
              清空
            </button>
          </div>
        </form>

        <div className="mt-2">
          <p className="text-[10px] uppercase text-slate-500 mb-1">示例</p>
          <div className="flex flex-wrap gap-1">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => useSuggestion(s)}
                className="text-[10px] px-1.5 py-0.5 bg-slate-100 hover:bg-slate-200 rounded text-slate-700"
                title={s}
              >
                {s.length > 22 ? s.slice(0, 22) + '…' : s}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-100 sticky top-0 flex items-center justify-between">
          <h3 className="text-xs font-semibold text-slate-600">
            论文列表 {papers.length > 0 && `(${papers.length})`}
          </h3>
          {papers.length > 0 && (
            <span className="text-[10px] text-slate-400">按相关性排序 · 点击打开</span>
          )}
        </div>
        {lastQuery && papers.length === 0 && (
          <p className="text-xs text-slate-400 p-4 text-center">未找到论文</p>
        )}
        <ul className="divide-y divide-slate-100">
          {papers.map((p, i) => (
            <li
              key={p.paper_id || i}
              className="px-3 py-1.5 hover:bg-slate-50 cursor-pointer transition"
              onClick={() => p.url && window.open(p.url, '_blank')}
              title={p.title}
            >
              <div className="flex items-start gap-2">
                <span className="text-[10px] font-mono text-slate-400 mt-0.5 shrink-0 w-5 text-right">
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-medium text-slate-800 line-clamp-2 leading-tight">
                    {p.title}
                  </p>
                  <div className="flex items-center gap-1.5 mt-0.5 text-[10px] text-slate-500">
                    <span>{p.year || '—'}</span>
                    <span>·</span>
                    <span>{p.citation_count.toLocaleString()}</span>
                    <span className="font-mono text-brand-600 font-semibold">
                      ★{p.final_score.toFixed(1)}
                    </span>
                    {p.is_expanded && (
                      <span className="ml-auto text-[9px] bg-amber-100 text-amber-700 px-1 rounded">
                        ext
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
