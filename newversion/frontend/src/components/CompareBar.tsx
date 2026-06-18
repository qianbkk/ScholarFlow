// CompareBar — slides up from the footer when 2 papers are selected.
// Side-by-side metadata + abstract. Push (not overlay) so the report reflows.

import { useStore } from '../hooks/useStore';
import { store } from '../state/store';
import type { Paper } from '../types';

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span
        className="mono text-[9px] uppercase"
        style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
      >
        {label}
      </span>
      <span className="mono text-[11px] tnum truncate" style={{ color: 'var(--ink-1)' }}>
        {value || '—'}
      </span>
    </div>
  );
}

function PaperColumn({ paper, index }: { paper: Paper; index: number }) {
  return (
    <div className="min-w-0 flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span
          className="mono tnum text-[10px]"
          style={{ color: 'var(--ink-3)' }}
        >
          {index.toString().padStart(2, '0')}
        </span>
        <h3
          className="display text-[12px] m-0"
          style={{ color: 'var(--ink-1)', fontWeight: 500 }}
        >
          {paper.title}
        </h3>
      </div>
      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
        <Field label="Year" value={String(paper.year)} />
        <Field label="Venue" value={paper.venue} />
        <Field label="Cites" value={paper.citation_count.toLocaleString()} />
        <Field label="Score" value={paper.final_score.toFixed(3)} />
      </div>
      {paper.abstract && (
        <p
          className="m-0 text-[11px] leading-relaxed"
          style={{ color: 'var(--ink-2)' }}
        >
          {paper.abstract.length > 280 ? paper.abstract.slice(0, 280) + '…' : paper.abstract}
        </p>
      )}
    </div>
  );
}

export function CompareBar() {
  const { result, selected } = useStore();
  if (!result) return null;
  const papers = result.ranked_papers.filter((p) => selected.includes(p.paper_id));
  if (papers.length < 2) return null;

  return (
    <section
      className="hairline-t"
      style={{ background: 'var(--surface-1)' }}
    >
      <div className="px-4 py-2 hairline-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className="mono text-[10px] uppercase"
            style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
          >
            compare
          </span>
          <span className="mono tnum text-[11px]" style={{ color: 'var(--ink-1)' }}>
            2 papers
          </span>
        </div>
        <button
          type="button"
          onClick={() => store.clearSelect()}
          className="mono text-[10px] uppercase"
          style={{
            background: 'transparent',
            color: 'var(--ink-2)',
            border: '1px solid var(--rule-strong)',
            padding: '2px 8px',
            letterSpacing: '0.14em',
          }}
        >
          clear
        </button>
      </div>
      <div className="grid gap-4 px-4 py-3" style={{ gridTemplateColumns: '1fr 1fr' }}>
        {papers.map((p, i) => (
          <PaperColumn key={p.paper_id} paper={p} index={i + 1} />
        ))}
      </div>
    </section>
  );
}
