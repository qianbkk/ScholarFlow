// PipelineStrip — the always-visible 8-node row. This is the v3
// differentiator. Active node is accent text + left bracket. Done is a
// checkmark in --signal-ok. Pending is --ink-3. Connector chevrons
// between nodes. v1/v2 had a status bar; v3 has the pipeline itself.

import { useStore } from '../hooks/useStore';

const ARROW = (
  <span
    aria-hidden
    className="mono text-[10px] mx-2 select-none"
    style={{ color: 'var(--ink-3)' }}
  >
    ›
  </span>
);

function Glyph({ status }: { status: string }) {
  if (status === 'done')
    return (
      <span className="mono" style={{ color: 'var(--signal-ok)' }}>
        ✓
      </span>
    );
  if (status === 'error')
    return (
      <span className="mono" style={{ color: 'var(--signal-err)' }}>
        ✕
      </span>
    );
  if (status === 'running')
    return (
      <span
        className="mono"
        style={{ color: 'var(--accent)' }}
        aria-label="running"
      >
        ●
      </span>
    );
  return (
    <span className="mono" style={{ color: 'var(--ink-3)' }}>
      ○
    </span>
  );
}

export function PipelineStrip() {
  const { nodes, running } = useStore();
  return (
    <div
      className="hairline-b flex items-center px-3 h-9 overflow-x-auto"
      style={{ background: 'var(--surface-1)' }}
    >
      <span
        className="mono text-[10px] uppercase mr-3 shrink-0"
        style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
      >
        pipeline
      </span>
      <ol className="flex items-center m-0 p-0 list-none">
        {nodes.map((n, i) => (
          <li key={n.node_id} className="flex items-center">
            <div
              className="flex items-center gap-1.5 px-2 py-1 mono text-[11px]"
              style={{
                color: n.status === 'pending' ? 'var(--ink-3)' : n.status === 'running' ? 'var(--accent)' : 'var(--ink-1)',
              }}
            >
              <Glyph status={n.status} />
              <span>{n.label}</span>
            </div>
            {i < nodes.length - 1 && ARROW}
          </li>
        ))}
      </ol>
      {!running && (
        <span
          className="ml-auto mono text-[10px] uppercase shrink-0"
          style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
        >
          idle
        </span>
      )}
    </div>
  );
}
