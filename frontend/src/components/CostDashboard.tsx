import type { SearchResult } from '../types';

interface Props {
  result: SearchResult | null;
  loading: boolean;
  elapsed: number;
}

export function CostDashboard({ result, loading, elapsed }: Props) {
  const cost = result?.total_cost_usd ?? 0;
  const tokens = result?.total_tokens_used ?? 0;
  const papers = result?.ranked_papers.length ?? 0;
  const iterations = result?.iteration ?? 0;
  const status = result?.status ?? (loading ? 'searching' : 'idle');

  const statusColor = {
    idle: 'bg-slate-400',
    searching: 'bg-amber-400 animate-pulse',
    done: 'bg-emerald-500',
    error: 'bg-rose-500',
  }[status] || 'bg-slate-400';

  return (
    <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-6 shadow-sm">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white font-bold text-sm">
          SF
        </div>
        <div>
          <h1 className="text-base font-semibold text-slate-900 leading-none">ScholarFlow</h1>
          <p className="text-xs text-slate-500 leading-none mt-0.5">科研文献智能搜索</p>
        </div>
      </div>

      <div className="h-8 w-px bg-slate-200" />

      <Stat label="Token" value={tokens.toLocaleString()} />
      <Stat label="Cost" value={`$${cost.toFixed(4)}`} />
      <Stat label="Papers" value={String(papers)} />
      <Stat label="Iterations" value={String(iterations)} />
      {elapsed > 0 && <Stat label="Elapsed" value={`${elapsed.toFixed(1)}s`} />}

      <div className="flex-1" />

      <div className="flex items-center gap-2 text-xs text-slate-600">
        <span className={`w-2 h-2 rounded-full ${statusColor}`} />
        <span className="capitalize">{status}</span>
      </div>
    </header>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
      <span className="text-sm font-semibold text-slate-800">{value}</span>
    </div>
  );
}
