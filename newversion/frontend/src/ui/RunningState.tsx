// RunningState — a centered progress view. Shows the query you asked and
// which node is currently running. Quiet, focused, no fake progress bar.

import { useStore } from '../hooks/useStore';
import { store } from '../state/store';

export function RunningState() {
  const { query, nodes, cost, tokens } = useStore();
  const current = nodes.find((n) => n.status === 'running');
  const done = nodes.filter((n) => n.status === 'done').length;

  return (
    <div
      className="flex-1 flex flex-col items-center justify-center px-6"
      style={{ background: 'var(--base)' }}
    >
      <div style={{ width: '100%', maxWidth: 'var(--read-max)' }}>
        <div
          className="mono text-[10px] uppercase mb-3"
          style={{ color: 'var(--ink-3)', letterSpacing: '0.22em' }}
        >
          running
        </div>

        <h1
          className="display m-0 mb-12"
          style={{
            fontSize: '1.75rem',
            fontWeight: 500,
            color: 'var(--ink-1)',
            letterSpacing: '-0.02em',
            lineHeight: 1.3,
          }}
        >
          {query}
        </h1>

        <ol className="m-0 p-0 list-none" style={{ borderTop: '1px solid var(--rule)' }}>
          {nodes.map((n, i) => (
            <li
              key={n.node_id}
              className="flex items-center justify-between py-3"
              style={{
                borderBottom: '1px solid var(--rule)',
                color:
                  n.status === 'running'
                    ? 'var(--accent)'
                    : n.status === 'done'
                    ? 'var(--ink-2)'
                    : 'var(--ink-3)',
              }}
            >
              <span className="flex items-center gap-3">
                <span
                  className="mono tnum text-[10px]"
                  style={{ minWidth: 22, color: 'var(--ink-3)' }}
                >
                  {(i + 1).toString().padStart(2, '0')}
                </span>
                <span
                  className="display"
                  style={{
                    fontSize: '15px',
                    fontWeight: n.status === 'running' ? 500 : 400,
                  }}
                >
                  {n.label}
                </span>
              </span>
              <span className="mono text-[10px] uppercase" style={{ letterSpacing: '0.14em' }}>
                {n.status === 'running' ? 'running' : n.status === 'done' ? '✓ done' : ''}
              </span>
            </li>
          ))}
        </ol>

        <div
          className="mt-6 flex items-center justify-between mono text-[11px]"
          style={{ color: 'var(--ink-3)' }}
        >
          <span>
            {done}/{nodes.length} complete
            {current && ` · ${current.label} in progress`}
          </span>
          <span>
            <span style={{ color: 'var(--ink-2)' }}>${cost.toFixed(4)}</span>
            <span style={{ color: 'var(--rule-strong)' }}> · </span>
            <span style={{ color: 'var(--ink-2)' }}>{tokens.toLocaleString()} tok</span>
          </span>
        </div>
      </div>
    </div>
  );
}
