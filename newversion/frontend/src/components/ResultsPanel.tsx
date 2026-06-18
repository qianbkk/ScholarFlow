// ResultsPanel — dense list of papers, no card chrome.
// 01-99 index in mono, title sans, authors+venue+year+cites in mono.
// Selected row: 2px left bracket in --accent + surface-2 background.

import { useStore } from '../hooks/useStore';
import { store } from '../state/store';
import type { Paper } from '../types';

export function ResultsPanel() {
  const { result, selected, hovered } = useStore();
  const papers: Paper[] = result?.ranked_papers ?? [];

  if (papers.length === 0) {
    return (
      <div
        className="mono text-[11px] py-6 px-3"
        style={{ color: 'var(--ink-3)' }}
      >
        no results — run a query above
      </div>
    );
  }

  return (
    <ol className="m-0 p-0 list-none">
      {papers.map((p, i) => {
        const isSelected = selected.includes(p.paper_id);
        const isHovered = hovered === p.paper_id;
        return (
          <li
            key={p.paper_id}
            className="hairline-b cursor-pointer bracket-l"
            style={{
              padding: '10px 12px 10px 14px',
              background: isSelected || isHovered ? 'var(--surface-2)' : 'transparent',
              color: 'var(--ink-1)',
            }}
            onClick={(e) => {
              if (e.shiftKey || e.metaKey) store.toggleSelect(p.paper_id);
            }}
            onMouseEnter={() => store.setHover(p.paper_id)}
            onMouseLeave={() => store.setHover(null)}
          >
            <div className="flex items-baseline gap-2.5">
              <span
                className="mono tnum text-[10px] shrink-0"
                style={{ color: 'var(--ink-3)', minWidth: 22 }}
              >
                {(i + 1).toString().padStart(2, '0')}
              </span>
              <div className="min-w-0 flex-1">
                <div
                  className="display text-[13px] leading-snug"
                  style={{ color: 'var(--ink-1)', fontWeight: 500 }}
                >
                  {p.title}
                </div>
                <div
                  className="mono text-[10px] mt-1 flex items-center gap-1.5 truncate"
                  style={{ color: 'var(--ink-2)' }}
                >
                  <span className="truncate">
                    {p.authors.slice(0, 3).join(', ')}
                    {p.authors.length > 3 ? ` +${p.authors.length - 3}` : ''}
                  </span>
                </div>
                <div
                  className="mono text-[10px] mt-0.5 flex items-center gap-1.5"
                  style={{ color: 'var(--ink-3)' }}
                >
                  <span>{p.year}</span>
                  <span style={{ color: 'var(--rule-strong)' }}>·</span>
                  <span style={{ fontStyle: 'italic' }}>{p.venue || '—'}</span>
                  <span style={{ color: 'var(--rule-strong)' }}>·</span>
                  <span className="tnum">{p.citation_count.toLocaleString()}c</span>
                  <span style={{ color: 'var(--rule-strong)' }}>·</span>
                  <span className="tnum">f={p.final_score.toFixed(2)}</span>
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
