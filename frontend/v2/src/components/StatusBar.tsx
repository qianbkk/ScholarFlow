// StatusBar — top, sticky. One row, mono font. Shows papers, tokens, cost, status, elapsed.
// NOT a hero-metric tile. NOT a gradient. Tabular figures.

import { useEffect, useState } from 'react';
import { useSearch } from '../contexts/SearchContext';

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function statusLabel(progressCount: number, loading: boolean, error: string | null): string {
  if (error) return error === 'cancelled' ? 'Cancelled' : 'Error';
  if (loading) return progressCount > 0 ? 'Synthesizing' : 'Starting';
  if (progressCount > 0) return 'Done';
  return 'Idle';
}

function statusColor(loading: boolean, error: string | null): string {
  if (error) return 'var(--signal-err)';
  if (loading) return 'var(--accent)';
  return 'var(--signal-ok)';
}

export function StatusBar() {
  const { state, cancel } = useSearch();
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!state.loading || !state.startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [state.loading, state.startedAt]);

  const elapsed = state.startedAt ? (now - state.startedAt) / 1000 : 0;
  const runningNodes = state.progress.filter((p) => p.status === 'running');
  const doneNodes = state.progress.filter((p) => p.status === 'done').length;
  const totalNodes = 8;

  return (
    <header
      className="sticky top-0 z-20 flex items-center justify-between px-6 h-12 hairline-b"
      style={{ background: 'var(--paper)' }}
    >
      <div className="flex items-center gap-5">
        <span className="display text-[15px] font-medium" style={{ color: 'var(--ink)' }}>
          ScholarFlow
        </span>
        <span
          className="status-dot"
          style={{ background: statusColor(state.loading, state.error) }}
          aria-hidden
        />
        <span className="mono text-[11px] uppercase tracking-[0.14em]" style={{ color: 'var(--ink-2)' }}>
          {statusLabel(state.progress.length, state.loading, state.error)}
        </span>
      </div>

      <div className="flex items-center gap-6 mono text-[11px] tnum" style={{ color: 'var(--ink-2)' }}>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>Papers</span>{' '}
          <span style={{ color: 'var(--ink)' }}>{state.result?.ranked_papers.length ?? 0}</span>
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>Nodes</span>{' '}
          <span style={{ color: 'var(--ink)' }}>
            {doneNodes}/{totalNodes}
          </span>
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>Tokens</span>{' '}
          <span style={{ color: 'var(--ink)' }}>{state.tokensUsed.toLocaleString()}</span>
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>Cost</span>{' '}
          <span style={{ color: 'var(--ink)' }}>${state.costUsd.toFixed(4)}</span>
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>Elapsed</span>{' '}
          <span style={{ color: 'var(--ink)' }}>{formatElapsed(elapsed)}</span>
        </span>
        {state.loading && (
          <button
            type="button"
            onClick={cancel}
            className="mono uppercase tracking-[0.14em] text-[10px] px-2 py-0.5"
            style={{
              background: 'transparent',
              color: 'var(--ink-2)',
              border: '1px solid var(--rule-strong)',
            }}
          >
            Cancel
          </button>
        )}
      </div>

      {/* Live progress strip — single line, no cards */}
      {state.loading && runningNodes.length > 0 && (
        <div
          className="absolute left-0 right-0 top-full px-6 py-1.5 mono text-[10px] flex items-center gap-3 hairline-b"
          style={{ background: 'var(--paper-elev)', color: 'var(--ink-2)' }}
        >
          <span style={{ color: 'var(--ink-3)' }}>Now:</span>
          {runningNodes.map((n) => (
            <span key={n.node_id} className="flex items-center gap-1.5">
              <span
                className="status-dot"
                style={{ background: 'var(--accent)' }}
                aria-hidden
              />
              <span style={{ color: 'var(--ink)' }}>{n.label}</span>
            </span>
          ))}
        </div>
      )}
    </header>
  );
}
