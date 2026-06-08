import type { SearchResult } from '../types';

interface Props {
  result: SearchResult | null;
  loading: boolean;
  elapsed: number;
  // R9 阶段 3 (审计员 #3): model_usage_summary 消费
  // App.tsx 暂时不显式传这个 prop, 我们从 result.model_usage_summary 回退读取.
  // 加 optional prop 是为了: 1) 测试时容易注入; 2) 未来 App.tsx 升级时不用再改这里.
  modelUsageSummary?: Record<string, { tokens: number; cost: number }>;
}

export function CostDashboard({ result, loading, elapsed, modelUsageSummary }: Props) {
  const cost = result?.total_cost_usd ?? 0;
  const tokens = result?.total_tokens_used ?? 0;
  const papers = result?.ranked_papers.length ?? 0;
  const iterations = result?.iteration ?? 0;
  const status = result?.status ?? (loading ? 'searching' : 'idle');
  // R9: model_usage_summary 字段消费. 优先用 prop, 其次 result.model_usage_summary
  // (R8 已升级), 最后回退到老字段 result.model_usage 兼容旧 cache.
  const usage =
    modelUsageSummary ?? result?.model_usage_summary ?? result?.model_usage ?? {};
  const usageEntries = Object.entries(usage).sort((a, b) => b[1].cost - a[1].cost);

  const statusColor = {
    idle: 'bg-slate-400',
    searching: 'bg-amber-400 animate-pulse',
    done: 'bg-emerald-500',
    error: 'bg-rose-500',
  }[status] || 'bg-slate-400';

  return (
    <>
      {/* R9 阶段 3 (审计员 #3): 移动端 375px 横向滚动修复
          之前 <header className="flex items-center gap-6"> 是单行横排, 5 个 Stat
          (Token/Cost/Papers/Iterations/Elapsed) + Logo + Status 在 375px 总宽
          ~625px, 触发 157px 横向滚动.
          修复:
            1) flex → flex-wrap + gap-4, 主 Stat (Cost/Status/Elapsed) 始终展示.
            2) 次要 Stat (Token/Papers/Iterations) 加 hidden sm:flex, 只在 ≥640px
               显示 — 移动端腾出空间, 桌面端信息密度不变.
            3) 边距 px-6 → px-4 sm:px-6, 移动端让出左右 padding. */}
      <header className="bg-[var(--sf-bg)] border-b border-slate-200 px-4 sm:px-6 py-3 flex flex-wrap items-center gap-4 shadow-sm">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white font-bold text-sm">
            SF
          </div>
          <div>
            <h1 className="text-base font-semibold text-slate-900 leading-none">ScholarFlow</h1>
            <p className="text-xs text-slate-500 leading-none mt-0.5">科研文献智能搜索</p>
          </div>
        </div>

        <div className="h-8 w-px bg-slate-200 hidden sm:block" />

        <Stat label="Token" value={tokens.toLocaleString()} className="hidden sm:flex" />
        <Stat label="Cost" value={`$${cost.toFixed(4)}`} />
        <Stat label="Papers" value={String(papers)} className="hidden sm:flex" />
        <Stat label="Iter" value={String(iterations)} className="hidden sm:flex" />
        {elapsed > 0 && <Stat label="Elapsed" value={`${elapsed.toFixed(1)}s`} />}

        <div className="flex-1" />

        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className={`w-2 h-2 rounded-full ${statusColor}`} />
          <span className="capitalize">{status}</span>
        </div>
      </header>

      {/* R9 阶段 3 (审计员 #3): per-model breakdown 折叠区
          之前 result.model_usage_summary 在 types 里声明了但 UI 不消费, R8 改的
          字段死在类型里. 现在 details/summary 折叠展示 (默认关闭, 不挤视觉),
          移动端也显示, 用户调试成本时可下钻到具体模型. */}
      {usageEntries.length > 0 && (
        <details
          className="bg-white border-b border-slate-200 px-4 sm:px-6 py-1.5 text-xs"
          data-testid="model-usage-breakdown"
        >
          <summary className="cursor-pointer text-slate-600 hover:text-slate-800 select-none list-none flex items-center gap-1.5">
            <span className="inline-block transition-transform group-open:rotate-90">
              ▸
            </span>
            <span>模型用量明细 ({usageEntries.length} 个)</span>
            <span className="text-slate-400 ml-1">
              · 累计 ${usageEntries.reduce((s, [, v]) => s + v.cost, 0).toFixed(4)}
            </span>
            {/* M-19 (R10.5) UI 差异化: 唯一可见 per-model 成本面板, 实时反映"哪个模型在烧钱",
               知网/Google Scholar/SS 都不显示. 用 amber 突出 "全网唯一" 信号. */}
            <span
              className="ml-2 text-amber-600 font-medium"
              title="其他工具 (知网/Google Scholar/Semantic Scholar) 都不显示 per-model 成本"
            >
              全网唯一可见
            </span>
          </summary>
          <div className="mt-1.5 grid gap-1">
            {usageEntries.map(([model, info]) => (
              <div
                key={model}
                className="flex items-center gap-2 sm:gap-3 text-slate-700"
              >
                <span className="font-mono text-[11px] flex-1 truncate" title={model}>
                  {model}
                </span>
                <span className="font-mono text-[11px] text-slate-500 w-20 sm:w-24 text-right">
                  {info.tokens.toLocaleString()} tok
                </span>
                <span className="font-mono text-[11px] text-brand-600 font-semibold w-16 sm:w-20 text-right">
                  ${info.cost.toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </>
  );
}

function Stat({
  label,
  value,
  className = '',
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={`flex flex-col ${className}`}>
      <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
      <span className="text-sm font-semibold text-slate-800">{value}</span>
    </div>
  );
}
