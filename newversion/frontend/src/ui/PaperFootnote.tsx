// PaperFootnote — the inline paper card. Lives inside the report flow
// when the user clicks a citation. NOT a side panel. NOT a modal.
// Just a card that appears below the citation, in the reading flow.

import { store } from '../state/store';
import type { Paper } from '../types';

interface Props {
  paper: Paper;
  index: number;
  onCompare: () => void;
}

export function PaperFootnote({ paper, index, onCompare }: Props) {
  const close = () => store.expandPaper(null);
  return (
    <aside
      className="my-6"
      style={{
        background: 'var(--surface-1)',
        border: '1px solid var(--rule)',
        borderLeft: '2px solid var(--accent)',
        padding: '20px 24px',
      }}
    >
      <div className="flex items-baseline justify-between mb-3">
        <div className="flex items-baseline gap-3 min-w-0">
          <span
            className="mono tnum shrink-0"
            style={{ color: 'var(--ink-3)', fontSize: '11px' }}
          >
            [{index.toString().padStart(2, '0')}]
          </span>
          <h4
            className="display m-0"
            style={{
              fontSize: '16px',
              fontWeight: 500,
              color: 'var(--ink-1)',
              letterSpacing: '-0.01em',
              lineHeight: 1.4,
            }}
          >
            {paper.title}
          </h4>
        </div>
        <button
          type="button"
          onClick={close}
          aria-label="close"
          className="mono shrink-0"
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--ink-3)',
            cursor: 'pointer',
            fontSize: '18px',
            padding: '0 4px',
            lineHeight: 1,
          }}
        >
          ×
        </button>
      </div>

      <div
        className="mono text-[11px] mb-3"
        style={{ color: 'var(--ink-2)' }}
      >
        {paper.authors.slice(0, 5).join(', ')}
        {paper.authors.length > 5 ? ` +${paper.authors.length - 5}` : ''}
        {' · '}
        {paper.year}
        {paper.venue ? ` · ${paper.venue}` : ''}
      </div>

      {paper.abstract && (
        <p
          className="m-0 mb-4"
          style={{
            fontSize: '13.5px',
            lineHeight: 1.65,
            color: 'var(--ink-2)',
            maxWidth: '60ch',
          }}
        >
          {paper.abstract}
        </p>
      )}

      <div
        className="flex items-center gap-5 mono text-[10px] tnum"
        style={{ color: 'var(--ink-3)' }}
      >
        <span>
          <span style={{ color: 'var(--ink-2)' }}>{paper.citation_count.toLocaleString()}</span> citations
        </span>
        <span>
          score <span style={{ color: 'var(--ink-2)' }}>{paper.final_score.toFixed(2)}</span>
        </span>
        {paper.doi && <span>doi: {paper.doi}</span>}
      </div>

      <div
        className="flex items-center gap-4 mt-4 pt-4"
        style={{ borderTop: '1px solid var(--rule)' }}
      >
        {paper.url && (
          <a
            href={paper.url}
            target="_blank"
            rel="noreferrer noopener"
            className="mono text-[11px]"
            style={{ color: 'var(--accent)' }}
          >
            open ↗
          </a>
        )}
        <button
          type="button"
          onClick={() => {
            store.toggleSelect(paper.paper_id);
            if (store.get().selected.length === 2) {
              onCompare();
            }
          }}
          className="mono text-[11px]"
          style={{ color: 'var(--accent)', background: 'transparent', border: 'none', padding: 0 }}
        >
          + compare
        </button>
        <button
          type="button"
          onClick={() => {
            store.setOverlay('graph');
            store.setHover(paper.paper_id);
          }}
          className="mono text-[11px]"
          style={{ color: 'var(--ink-2)', background: 'transparent', border: 'none', padding: 0 }}
        >
          see in graph
        </button>
      </div>
    </aside>
  );
}
