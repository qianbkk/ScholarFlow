// CompareDrawer — bottom of report column when 2 papers are selected.
// Side-by-side metadata + abstract. NOT a modal, NOT a slide-in.
// Just a sticky bar that appears when 2 papers are selected.

import { useSearch } from '../contexts/SearchContext';
import { useSelection } from '../contexts/SelectionContext';
import type { Paper } from '../types/domain';

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span
        className="mono text-[9px] uppercase tracking-[0.18em]"
        style={{ color: 'var(--ink-3)' }}
      >
        {label}
      </span>
      <span className="mono text-[12px]" style={{ color: 'var(--ink)' }}>
        {value || '—'}
      </span>
    </div>
  );
}

function PaperColumn({ paper, index }: { paper: Paper; index: number }) {
  return (
    <div className="min-w-0 flex-1 flex flex-col gap-3">
      <div className="flex items-baseline gap-2">
        <span className="mono tnum text-[10px]" style={{ color: 'var(--ink-3)' }}>
          {index.toString().padStart(2, '0')}
        </span>
        <h3
          className="display text-[14px] m-0"
          style={{ color: 'var(--ink)', fontWeight: 500 }}
        >
          {paper.title}
        </h3>
      </div>
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}
      >
        <Field label="Authors" value={paper.authors.join(', ')} />
        <Field label="Year" value={String(paper.year)} />
        <Field label="Venue" value={paper.venue} />
        <Field label="Citations" value={paper.citation_count.toLocaleString()} />
        <Field label="Source" value={paper.source} />
        <Field label="Score" value={paper.final_score.toFixed(3)} />
      </div>
      {paper.abstract && (
        <div>
          <span
            className="mono text-[9px] uppercase tracking-[0.18em] block mb-1"
            style={{ color: 'var(--ink-3)' }}
          >
            Abstract
          </span>
          <p
            className="m-0 text-[12px] leading-relaxed"
            style={{ color: 'var(--ink-2)' }}
          >
            {paper.abstract.length > 500
              ? paper.abstract.slice(0, 500) + '…'
              : paper.abstract}
          </p>
        </div>
      )}
      {paper.url && (
        <a
          href={paper.url}
          target="_blank"
          rel="noreferrer noopener"
          className="mono text-[11px]"
          style={{ color: 'var(--accent)' }}
        >
          Open ↗
        </a>
      )}
    </div>
  );
}

export function CompareDrawer() {
  const { state } = useSearch();
  const { state: selState, deselect, clear } = useSelection();

  const selected = state.result?.ranked_papers.filter((p) => selState.selectedIds.includes(p.paper_id)) ?? [];

  if (selected.length < 2) return null;

  return (
    <aside
      className="sticky bottom-0 hairline-t mt-8"
      style={{ background: 'var(--paper-elev)' }}
    >
      <div className="px-6 py-4 flex items-center justify-between hairline-b">
        <div className="flex items-center gap-3">
          <span
            className="mono text-[10px] uppercase tracking-[0.18em]"
            style={{ color: 'var(--ink-3)' }}
          >
            Compare
          </span>
          <span className="mono tnum text-[12px]" style={{ color: 'var(--ink)' }}>
            2 papers
          </span>
        </div>
        <button
          type="button"
          onClick={clear}
          className="mono text-[10px] uppercase tracking-[0.14em] px-2 py-0.5"
          style={{ background: 'transparent', color: 'var(--ink-2)', border: '1px solid var(--rule-strong)' }}
        >
          Clear
        </button>
      </div>
      <div className="grid gap-6 px-6 py-5" style={{ gridTemplateColumns: '1fr 1fr' }}>
        {selected.map((p, i) => (
          <div key={p.paper_id} className="flex flex-col gap-3 min-w-0">
            <PaperColumn paper={p} index={i + 1} />
            <button
              type="button"
              onClick={() => deselect(p.paper_id)}
              className="self-start mono text-[10px] uppercase tracking-[0.14em] px-2 py-0.5"
              style={{ background: 'transparent', color: 'var(--ink-2)', border: '1px solid var(--rule-strong)' }}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}
