// CompareOverlay — fullscreen 2-paper side-by-side. Pressed from any
// paper card or from the footer ⌘K → "compare selected" affordance.

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
      <span className="mono text-[12px] tnum truncate" style={{ color: 'var(--ink-1)' }}>
        {value || '—'}
      </span>
    </div>
  );
}

function Column({ paper, index }: { paper: Paper; index: number }) {
  return (
    <div className="min-w-0 flex flex-col gap-5">
      <div className="flex items-baseline gap-3">
        <span
          className="mono tnum text-[11px]"
          style={{ color: 'var(--ink-3)' }}
        >
          {index.toString().padStart(2, '0')}
        </span>
        <h3
          className="display m-0"
          style={{
            fontSize: '1.4rem',
            fontWeight: 500,
            color: 'var(--ink-1)',
            letterSpacing: '-0.015em',
            lineHeight: 1.3,
          }}
        >
          {paper.title}
        </h3>
      </div>

      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
        <Field label="Authors" value={paper.authors.join(', ')} />
        <Field label="Year" value={String(paper.year)} />
        <Field label="Venue" value={paper.venue} />
        <Field label="Citations" value={paper.citation_count.toLocaleString()} />
        <Field label="Source" value={paper.source} />
        <Field label="Final score" value={paper.final_score.toFixed(3)} />
        <Field label="Relevance" value={paper.relevance_score.toFixed(3)} />
        <Field label="DOI" value={paper.doi ?? '—'} />
      </div>

      {paper.abstract && (
        <div>
          <div
            className="mono text-[9px] uppercase mb-2"
            style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
          >
            abstract
          </div>
          <p
            className="m-0"
            style={{
              fontSize: '14px',
              lineHeight: 1.7,
              color: 'var(--ink-2)',
              maxWidth: '60ch',
            }}
          >
            {paper.abstract}
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
          open paper ↗
        </a>
      )}
    </div>
  );
}

export function CompareOverlay() {
  const { result, selected } = useStore();
  if (!result) return null;
  const papers = result.ranked_papers.filter((p) => selected.includes(p.paper_id));
  if (papers.length < 2) return null;

  return (
    <div className="flex flex-col h-full">
      <div
        className="hairline-b flex items-center justify-between px-6 h-12 shrink-0"
        style={{ background: 'var(--base)' }}
      >
        <div className="flex items-center gap-3">
          <span
            className="mono text-[10px] uppercase"
            style={{ color: 'var(--ink-3)', letterSpacing: '0.22em' }}
          >
            compare
          </span>
          <span className="mono tnum text-[11px]" style={{ color: 'var(--ink-1)' }}>
            2 papers
          </span>
        </div>
        <button
          type="button"
          onClick={() => {
            store.clearSelect();
            store.setOverlay(null);
          }}
          className="mono text-[10px] uppercase"
          style={{
            background: 'transparent',
            color: 'var(--ink-2)',
            border: '1px solid var(--rule-strong)',
            padding: '4px 10px',
            letterSpacing: '0.14em',
          }}
        >
          close
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-10">
        <div
          className="mx-auto grid gap-12"
          style={{ maxWidth: 'var(--read-max)', gridTemplateColumns: '1fr 1fr' }}
        >
          {papers.map((p, i) => (
            <Column key={p.paper_id} paper={p} index={i + 1} />
          ))}
        </div>
      </div>
    </div>
  );
}
