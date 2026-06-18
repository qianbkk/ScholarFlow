// Footer — bottom 32px. ⌘ shortcuts on the left, telemetry on the right.
// Hairline top.

import { useEffect, useState } from 'react';
import { useStore } from '../hooks/useStore';
import { store } from '../state/store';

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export function Footer() {
  const { cost, tokens, startedAt, mode, result, error, nodes } = useStore();
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (mode !== 'running' || !startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [mode, startedAt]);

  const elapsed = startedAt ? (now - startedAt) / 1000 : result?.elapsed_seconds ?? 0;
  const doneNodes = nodes.filter((n) => n.status === 'done').length;
  const totalNodes = nodes.length;
  const graphReady = result && result.citation_graph.nodes.length > 0;

  return (
    <footer
      className="hairline-t flex items-center justify-between px-6 h-8 shrink-0"
      style={{ background: 'var(--base)' }}
    >
      <div
        className="flex items-center gap-5 mono text-[10px] tnum"
        style={{ color: 'var(--ink-3)' }}
      >
        <button
          type="button"
          disabled={mode !== 'done'}
          onClick={() => store.setOverlay('graph')}
          className="mono text-[10px] uppercase"
          style={{
            background: 'transparent',
            color: graphReady ? 'var(--ink-2)' : 'var(--ink-3)',
            border: 'none',
            padding: 0,
            letterSpacing: '0.14em',
            cursor: graphReady ? 'pointer' : 'default',
          }}
        >
          <span style={{ color: 'var(--accent)' }}>⌘G</span> graph
          {graphReady && (
            <span style={{ color: 'var(--ink-3)', marginLeft: 6 }}>
              {result?.citation_graph.metadata.total_papers}n / {result?.citation_graph.metadata.total_links}e
            </span>
          )}
        </button>
        <button
          type="button"
          disabled={mode !== 'done'}
          onClick={() => store.setOverlay('papers')}
          className="mono text-[10px] uppercase"
          style={{
            background: 'transparent',
            color: result ? 'var(--ink-2)' : 'var(--ink-3)',
            border: 'none',
            padding: 0,
            letterSpacing: '0.14em',
            cursor: result ? 'pointer' : 'default',
          }}
        >
          <span style={{ color: 'var(--accent)' }}>⌘P</span> papers
          {result && (
            <span style={{ color: 'var(--ink-3)', marginLeft: 6 }}>
              {result.ranked_papers.length}
            </span>
          )}
        </button>
        <span
          className="mono text-[10px] uppercase"
          style={{ color: 'var(--ink-3)', letterSpacing: '0.14em' }}
        >
          <span style={{ color: 'var(--accent)' }}>⌘E</span> export
        </span>
      </div>

      <div
        className="flex items-center gap-4 mono text-[10px] tnum"
        style={{ color: 'var(--ink-2)' }}
      >
        {error && (
          <span style={{ color: 'var(--signal-err)' }}>{error}</span>
        )}
        <span>
          <span style={{ color: 'var(--ink-3)' }}>cost</span> ${cost.toFixed(4)}
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>tokens</span> {tokens.toLocaleString()}
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>elapsed</span> {fmt(elapsed)}
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>nodes</span> {doneNodes}/{totalNodes}
        </span>
      </div>
    </footer>
  );
}
