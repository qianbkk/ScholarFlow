// PapersDrawer — ⌘P. Right-edge 360px drawer showing the ranked list.
// Click a paper -> close drawer + expand that paper in the report.

import { useStore } from '../hooks/useStore';
import { store } from '../state/store';
import type { Paper } from '../types';

export function PapersDrawer() {
  const { result, hovered } = useStore();
  if (!result) return null;
  const sorted = [...result.ranked_papers].sort((a, b) => b.final_score - a.final_score);

  return (
    <div
      className="flex flex-col h-full"
      style={{ background: 'var(--surface-1)' }}
    >
      <div
        className="hairline-b flex items-center justify-between px-5 h-12 shrink-0"
      >
        <div className="flex items-baseline gap-3">
          <span
            className="mono text-[10px] uppercase"
            style={{ color: 'var(--ink-3)', letterSpacing: '0.22em' }}
          >
            papers
          </span>
          <span
            className="mono tnum text-[11px]"
            style={{ color: 'var(--ink-1)' }}
          >
            {sorted.length}
          </span>
        </div>
        <button
          type="button"
          onClick={() => store.setOverlay(null)}
          className="mono"
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--ink-3)',
            cursor: 'pointer',
            fontSize: '18px',
            padding: 0,
            lineHeight: 1,
          }}
          aria-label="close"
        >
          ×
        </button>
      </div>

      <ol className="m-0 p-0 list-none flex-1 overflow-y-auto">
        {sorted.map((p, i) => (
          <li
            key={p.paper_id}
            className="hairline-b cursor-pointer"
            style={{
              padding: '14px 20px',
              background: hovered === p.paper_id ? 'var(--surface-2)' : 'transparent',
            }}
            onClick={() => {
              store.expandPaper(p.paper_id);
              store.setOverlay(null);
            }}
            onMouseEnter={() => store.setHover(p.paper_id)}
            onMouseLeave={() => store.setHover(null)}
          >
            <Row paper={p} index={i + 1} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function Row({ paper, index }: { paper: Paper; index: number }) {
  return (
    <div>
      <div className="flex items-baseline gap-2.5">
        <span
          className="mono tnum shrink-0"
          style={{ color: 'var(--ink-3)', minWidth: 22, fontSize: '10px' }}
        >
          {index.toString().padStart(2, '0')}
        </span>
        <h3
          className="display m-0"
          style={{
            fontSize: '13.5px',
            fontWeight: 500,
            color: 'var(--ink-1)',
            lineHeight: 1.4,
            letterSpacing: '-0.005em',
          }}
        >
          {paper.title}
        </h3>
      </div>
      <div
        className="mono text-[10px] mt-1.5 truncate"
        style={{ color: 'var(--ink-2)' }}
      >
        {paper.authors.slice(0, 3).join(', ')}
        {paper.authors.length > 3 ? ` +${paper.authors.length - 3}` : ''}
      </div>
      <div
        className="mono text-[10px] mt-1 flex items-center gap-1.5"
        style={{ color: 'var(--ink-3)' }}
      >
        <span>{paper.year}</span>
        <span style={{ color: 'var(--rule-strong)' }}>·</span>
        <span style={{ fontStyle: 'italic' }}>{paper.venue || '—'}</span>
        <span style={{ color: 'var(--rule-strong)' }}>·</span>
        <span className="tnum">{paper.citation_count.toLocaleString()}c</span>
        <span style={{ color: 'var(--rule-strong)' }}>·</span>
        <span className="tnum">f={paper.final_score.toFixed(2)}</span>
      </div>
    </div>
  );
}
