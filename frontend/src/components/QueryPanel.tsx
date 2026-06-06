import { useEffect, useState } from 'react';
import type { Paper } from '../types';
import { fetchProviders, type ProviderInfo } from '../services/api';

interface PipelineStep {
  key: string;
  label: string;
  emoji: string;
}

interface Props {
  loading: boolean;
  onSearch: (query: string, budget: number, maxIter: number, provider?: string) => void;
  onReset: () => void;
  papers: Paper[];
  lastQuery: string;
  currentStep?: number;
  elapsedSec?: number;
  pipelineSteps?: PipelineStep[];
  // Round 5 SIMPLIFY (API-001): 后端 M-1 已发 is_degraded_response + fallback_paper_count
  // 顶层字段, 前端直接用, 替代之前从 papers[].is_fallback 单篇聚合的 useMemo 派生.
  isDegradedResponse?: boolean;
  fallbackPaperCount?: number;
}

const SUGGESTIONS = [
  'transformer attention mechanism',
  '大语言模型在代码生成中的应用',
  'multi-agent reinforcement learning coordination',
  'retrieval augmented generation survey',
  'chain of thought reasoning in LLMs',
];

export function QueryPanel({
  loading, onSearch, onReset, papers, lastQuery,
  currentStep = 0, elapsedSec = 0, pipelineSteps = [],
  isDegradedResponse = false, fallbackPaperCount = 0,
}: Props) {
  const [query, setQuery] = useState('');
  const [budget, setBudget] = useState(2.0);
  const [maxIter, setMaxIter] = useState(3);
  // LLM provider 选择 — 拉取后端 /providers 列表（仅 has_key=true 可见）
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [defaultProvider, setDefaultProvider] = useState<string>('');
  const [selectedProvider, setSelectedProvider] = useState<string>('');  // 空 = 用默认
  const [providersLoading, setProvidersLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setProvidersLoading(true);
    fetchProviders()
      .then((resp) => {
        if (cancelled) return;
        setProviders(resp.providers.filter((p) => p.has_key));
        setDefaultProvider(resp.default_provider);
        // 初始化为默认 provider（如果有 key），否则保持空
        const def = resp.providers.find(
          (p) => p.id === resp.default_provider && p.has_key
        );
        if (def) setSelectedProvider(def.id);
      })
      .catch((err) => {
        // 静默失败：provider 下拉为空时回退到后端默认
        console.warn('fetchProviders failed:', err);
      })
      .finally(() => {
        if (!cancelled) setProvidersLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    onSearch(query, budget, maxIter, selectedProvider || undefined);
  };

  const useSuggestion = (s: string) => {
    setQuery(s);
  };

  const handleReset = () => {
    setQuery("");
    setBudget(2.0);
    setMaxIter(3);
    setSelectedProvider(defaultProvider);
    onReset();
  };

  return (
    {/* Round 6 S5: 移动端 w-full, lg+ 切回 1/4 宽 + 280px 最小宽.
        高度也变 h-auto (移动端跟随内容) vs h-full (桌面 flex 子项填满). */}
    <aside className="w-full lg:w-1/4 lg:min-w-[280px] h-auto lg:h-full bg-white border-r border-slate-200 flex flex-col">
      <div className="p-3 border-b border-slate-100">
        <h2 className="text-sm font-semibold text-slate-700 mb-2">研究查询</h2>
        <form onSubmit={submit} className="space-y-2">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入研究问题（中英文均可）..."
            rows={2}
            maxLength={2000}
            className="w-full text-sm border border-slate-300 rounded-md p-2 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent resize-none"
          />
          {/* Round 4 U3: 实时字符计数，防止超长 query 触发后端 400
              > 1800 变橙色（警告接近上限），= 2000 变红色（已到硬上限）。 */}
          <div
            className={`text-xs mt-1 text-right ${
              query.length >= 2000
                ? 'text-red-600 font-medium'
                : query.length > 1800
                ? 'text-orange-500'
                : 'text-slate-400'
            }`}
            aria-live="polite"
          >
            {query.length}/2000
          </div>

          <div className="flex items-center gap-2 text-xs">
            <label className="flex items-center gap-1 text-slate-600">
              模型
              <select
                value={selectedProvider}
                onChange={(e) => setSelectedProvider(e.target.value)}
                disabled={providersLoading}
                title={providersLoading ? '加载中…' : '选择 LLM provider（仅显示已配置 key 的）'}
                className="border border-slate-300 rounded px-1.5 py-0.5 text-xs max-w-[120px] focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                {providers.length === 0 && !providersLoading && (
                  <option value="">（无可用 provider）</option>
                )}
                {providers.map((p) => (
                  <option key={p.id} value={p.id} title={p.flagship_model}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
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
          </div>

          <div className="flex items-center gap-2 text-xs">
            {/* Round 6 S1: loading 时 search 按钮变取消按钮, 闭环 Round 5 S-5 后端 cancel.
                之前 loading 期间用户无法中断 8 节点流水线 (SSE + LLM 调用可能跑 30s+),
                按钮文案 '搜索中...' 误导用户以为在排队, 实际无取消能力.
                现在 loading 时:
                  - 按钮文案 '搜索中…' → '取消'
                  - 颜色 brand-600 → rose-600 (语义化危险动作)
                  - 行为 onClick(onReset) → 触发 useSearch.reset → POST /api/search/cancel
                注意 type='button' (不是 'submit'), 避免点取消时误触发表单 submit. */}
            {loading ? (
              <button
                type="button"
                onClick={onReset}
                aria-label="取消当前搜索"
                className="flex-1 bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium py-1.5 rounded-md transition"
              >
                取消
              </button>
            ) : (
              <button
                type="submit"
                disabled={!query.trim()}
                className="flex-1 bg-brand-600 hover:bg-brand-700 disabled:bg-slate-300 text-white text-sm font-medium py-1.5 rounded-md transition"
              >
                搜索
              </button>
            )}
            <button
              type="button"
              onClick={handleReset}
              disabled={loading}
              className="px-2.5 py-1.5 text-sm border border-slate-300 rounded-md hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
              title={loading ? '请先取消当前搜索' : '清空表单'}
            >
              清空
            </button>
          </div>
        </form>

        {loading && (
          <div className="mt-2 p-2 bg-brand-50 border border-brand-200 rounded-md">
            <div className="flex items-center justify-between text-[10px] text-brand-700 mb-1.5">
              <span className="font-medium">
                {pipelineSteps[currentStep]?.emoji} {pipelineSteps[currentStep]?.label}
              </span>
              <span className="font-mono">{elapsedSec.toFixed(1)}s</span>
            </div>
            <div className="grid grid-cols-4 gap-0.5">
              {pipelineSteps.map((s, i) => (
                <div
                  key={s.key}
                  className={`h-1 rounded ${
                    i < currentStep
                      ? 'bg-brand-500'
                      : i === currentStep
                      ? 'bg-brand-300 animate-pulse'
                      : 'bg-slate-200'
                  }`}
                />
              ))}
            </div>
          </div>
        )}

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
        {/* Round 5 SIMPLIFY (API-001): 切到 M-1 顶层字段
            is_degraded_response / fallback_paper_count 直接来自后端 SearchResponse
            (Round 5 M-1, commit 0754fa1), 替代之前从 papers[].is_fallback 单篇聚合的 useMemo 派生.
            闭环后端 API + 减 1 个 useMemo. */}
        {isDegradedResponse && (
          <div
            className="bg-amber-50 border-l-4 border-amber-400 text-amber-800 px-4 py-3 mx-3 mt-3 rounded-md flex items-start gap-3"
            role="alert"
            data-testid="degraded-banner"
          >
            <span className="text-amber-600 text-xl leading-none" role="img" aria-label="warning">⚠️</span>
            <div className="flex-1">
              <h4 className="font-semibold text-sm">部分结果来自后备数据</h4>
              <p className="text-xs mt-1 text-amber-700">
                本次搜索触发了 {fallbackPaperCount} 篇论文的后备 fallback
                （可能因 LLM API 限流、key 失效或网络问题）。建议检查 provider 配置后重试。
              </p>
            </div>
          </div>
        )}
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
              onClick={() => {
                // BUG-003 / VULN-004 修复：URL 协议白名单 + noopener/noreferrer
                if (p.url && /^https?:\/\//i.test(p.url)) {
                  window.open(p.url, '_blank', 'noopener,noreferrer');
                }
              }}
              title={p.title}
            >
              <div className="flex items-start gap-2">
                <span className="text-[10px] font-mono text-slate-400 mt-0.5 shrink-0 w-5 text-right">
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-1.5">
                    <p className="text-[11px] font-medium text-slate-800 line-clamp-2 leading-tight flex-1">
                      {p.title}
                    </p>
                    {/* P0-2 修复：单篇论文来自 fallback 时，title 旁加醒目标记 */}
                    {p.is_fallback && (
                      <span
                        className="shrink-0 inline-block bg-amber-100 text-amber-700 text-[9px] px-1.5 py-0.5 rounded font-medium"
                        title="此论文来自后备 fallback 数据（非真实 API 检索）"
                        data-testid="paper-fallback-badge"
                      >
                        后备
                      </span>
                    )}
                  </div>
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
