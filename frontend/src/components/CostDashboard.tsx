/**
 * CostDashboard — 报头下方"运行指标条" (R10.5.4 Editorial)
 *
 * 设计意图: 学术期刊"运行状态"行 — 像 Bloomberg 终端的精简版
 *   - 刊号: 大字 Fraunces 数字 (Cost / Tokens / Papers)
 *   - 副标: IBM Plex Sans 10px UPPERCASE + letter-spacing (Cost / TOKEN / etc.)
 *   - 状态: 一个小竖条 + 文字 (idle / searching / done / error)
 *   - 折叠区: 模型用量明细 (用 editorial 的 fine rule 风格)
 */
import type { SearchResult } from '../types';

interface Props {
  result: SearchResult | null;
  loading: boolean;
  elapsed: number;
  modelUsageSummary?: Record<string, { tokens: number; cost: number }>;
}

export function CostDashboard({ result, loading, elapsed, modelUsageSummary }: Props) {
  const cost = result?.total_cost_usd ?? 0;
  const tokens = result?.total_tokens_used ?? 0;
  const papers = result?.ranked_papers.length ?? 0;
  const iterations = result?.iteration ?? 0;
  const status = result?.status ?? (loading ? 'searching' : 'idle');
  const usage =
    modelUsageSummary ?? result?.model_usage_summary ?? result?.model_usage ?? {};
  const usageEntries = Object.entries(usage)
    .map(([k, v]) => [k, { tokens: v?.tokens ?? 0, cost: v?.cost ?? 0 }] as const)
    .sort((a, b) => b[1].cost - a[1].cost);

  const statusMeta: Record<string, { label: string; color: string; dot: string }> = {
    idle: { label: '待命中', color: 'var(--sf-muted)', dot: 'var(--sf-border)' },
    searching: { label: '检索中', color: 'var(--sf-accent)', dot: 'var(--sf-accent)' },
    done: { label: '已完成', color: 'var(--sf-text)', dot: 'var(--sf-text)' },
    error: { label: '出错了', color: 'var(--sf-accent)', dot: 'var(--sf-accent)' },
  };
  const meta = statusMeta[status] || statusMeta.idle;

  return (
    <>
      {/* R10.5.4 Editorial: 指标条用更"印刷"的网格 — 等宽分栏 + 细线分隔.
          每个指标 12px uppercase 副标 + Fraunces 24px 数字 (tabular-nums).
          用 var(--sf-bg-elev) 做轻微底色差, 跟 paper bg 拉开层次. */}
      <div
        className="px-4 sm:px-6 py-2.5 flex flex-wrap items-baseline gap-x-6 sm:gap-x-8 gap-y-2 border-b"
        style={{
          backgroundColor: 'var(--sf-bg-elev)',
          borderColor: 'var(--sf-border)',
        }}
      >
        {/* 刊号 SECTION: 大数字 + 极小标 */}
        <Metric label="费用" value={`$${cost.toFixed(4)}`} emphasis />
        <Divider />
        <Metric label="Tokens" value={tokens.toLocaleString()} className="hidden sm:flex" />
        <Divider className="hidden sm:block" />
        <Metric label="论文" value={String(papers)} className="hidden sm:flex" />
        <Divider className="hidden sm:block" />
        <Metric label="迭代" value={String(iterations)} className="hidden sm:flex" />
        {elapsed > 0 && (
          <>
            <Divider />
            <Metric label="耗时" value={`${elapsed.toFixed(1)}s`} />
          </>
        )}

        <div className="flex-1" />

        {/* 状态: 左侧细色条 + mono 文字 */}
        <div
          className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.15em]"
          style={{ color: meta.color }}
        >
          <span
            className={`inline-block w-1.5 h-3.5 ${status === 'searching' ? 'animate-pulse' : ''}`}
            style={{ backgroundColor: meta.dot }}
          />
          <span>{meta.label}</span>
        </div>
      </div>

      {/* 模型用量明细 — 折叠区, Editorial 风格的 fine rule + tabular 数据 */}
      {usageEntries.length > 0 && (
        <details
          className="px-4 sm:px-6 py-2 text-xs font-ui border-b"
          style={{ borderColor: 'var(--sf-border)' }}
          data-testid="model-usage-breakdown"
        >
          <summary
            className="cursor-pointer select-none flex items-center gap-2 hover:opacity-80 transition"
            style={{ color: 'var(--sf-muted)' }}
          >
            <span className="font-mono text-[10px]">▸</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.15em]">
              模型用量明细 ({usageEntries.length})
            </span>
            <span className="font-mono text-[10px]" style={{ color: 'var(--sf-muted)' }}>
              · 累计 ${usageEntries.reduce((s, [, v]) => s + v.cost, 0).toFixed(4)}
            </span>
          </summary>
          <div className="mt-2 grid gap-1 pl-4">
            {usageEntries.map(([model, info]) => (
              <div
                key={model}
                className="flex items-baseline gap-3 sm:gap-4"
                style={{ color: 'var(--sf-text)' }}
              >
                <span
                  className="font-mono text-[11px] flex-1 truncate"
                  style={{ color: 'var(--sf-muted)' }}
                  title={model}
                >
                  {model}
                </span>
                <span
                  className="font-mono text-[11px] tabular-nums w-20 sm:w-28 text-right"
                  style={{ color: 'var(--sf-muted)' }}
                >
                  {(info.tokens ?? 0).toLocaleString()} tok
                </span>
                <span
                  className="font-mono text-[11px] tabular-nums w-16 sm:w-20 text-right font-medium"
                  style={{ color: 'var(--sf-accent)' }}
                >
                  ${(info.cost ?? 0).toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </>
  );
}

function Metric({
  label,
  value,
  className = '',
  emphasis = false,
}: {
  label: string;
  value: string;
  className?: string;
  emphasis?: boolean;
}) {
  return (
    <div className={`flex flex-col leading-tight ${className}`}>
      <span
        className="text-[9px] uppercase tracking-[0.18em] font-mono mb-0.5"
        style={{ color: 'var(--sf-muted)' }}
      >
        {label}
      </span>
      <span
        className={`tabular-nums ${
          emphasis ? 'font-display text-xl' : 'font-mono text-sm font-medium'
        }`}
        style={{ color: emphasis ? 'var(--sf-text)' : 'var(--sf-text)' }}
      >
        {value}
      </span>
    </div>
  );
}

function Divider({ className = '' }: { className?: string }) {
  return (
    <div
      className={`self-stretch w-px ${className}`}
      style={{ backgroundColor: 'var(--sf-border)' }}
      aria-hidden="true"
    />
  );
}
