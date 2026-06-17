// PaperList — a list of papers from the current result.
// NOT a card grid. Numbered rows with hairline rules.
// Selected row: 2px left rule + accent-soft background.
// Hover: ink-2 color shift, NOT a scale animation.

import { useMemo } from 'react';
import type { Paper } from '../types/domain';
import { useSelection } from '../contexts/SelectionContext';

interface Props {
  papers: Paper[];
  onHoverPaper?: (id: string | null) => void;
  activeId?: string | null;
}

export function PaperList({ papers, onHoverPaper, activeId }: Props) {
  const { toggle, isSelected } = useSelection();

  const sorted = useMemo(
    () => [...papers].sort((a, b) => b.final_score - a.final_score),
    [papers],
  );

  if (sorted.length === 0) {
    return (
      <div
        className="mono text-[12px] py-8 px-2"
        style={{ color: 'var(--ink-3)' }}
      >
        No papers yet. Run a search to see results.
      </div>
    );
  }

  return (
    <ol className="m-0 p-0 list-none">
      {sorted.map((p, i) => {
        const selected = isSelected(p.paper_id);
        const active = activeId === p.paper_id;
        return (
          <li
            key={p.paper_id}
            className="relative cursor-pointer hairline-b transition-colors duration-150 ease-out-expo"
            style={{
              padding: '14px 14px 14px 18px',
              background: selected
                ? 'var(--accent-soft)'
                : active
                ? 'var(--paper-elev)'
                : 'transparent',
            }}
            onMouseEnter={() => onHoverPaper?.(p.paper_id)}
            onMouseLeave={() => onHoverPaper?.(null)}
            onClick={(e) => {
              if (e.shiftKey || e.metaKey) toggle(p.paper_id);
            }}
            data-testid={`paper-row-${i}`}
          >
            {selected && (
              <span
                aria-hidden
                className="absolute left-0 top-0 bottom-0"
                style={{ width: 2, background: 'var(--accent)' }}
              />
            )}
            <div className="flex items-baseline gap-3">
              <span
                className="mono tnum text-[11px] shrink-0"
                style={{ color: 'var(--ink-3)', minWidth: 22 }}
              >
                {(i + 1).toString().padStart(2, '0')}
              </span>
              <div className="min-w-0 flex-1">
                <h3
                  className="display text-[15px] leading-snug m-0"
                  style={{
                    color: 'var(--ink)',
                    fontWeight: 500,
                    letterSpacing: '-0.01em',
                  }}
                >
                  {p.title}
                </h3>
                <div
                  className="mono text-[11px] mt-1.5 flex items-center gap-2"
                  style={{ color: 'var(--ink-2)' }}
                >
                  <span>
                    {p.authors.slice(0, 3).join(', ')}
                    {p.authors.length > 3 ? ` +${p.authors.length - 3}` : ''}
                  </span>
                  <span style={{ color: 'var(--rule-strong)' }}>·</span>
                  <span>{p.year}</span>
                  {p.venue && (
                    <>
                      <span style={{ color: 'var(--rule-strong)' }}>·</span>
                      <span style={{ fontStyle: 'italic' }}>{p.venue}</span>
                    </>
                  )}
                </div>
                <div
                  className="mono text-[10px] mt-1.5 flex items-center gap-2"
                  style={{ color: 'var(--ink-3)' }}
                >
                  <span className="tnum">{p.citation_count.toLocaleString()} cites</span>
                  <span style={{ color: 'var(--rule-strong)' }}>·</span>
                  <span className="tnum">score {p.final_score.toFixed(2)}</span>
                  {p.is_fallback && (
                    <span
                      className="tnum ml-1"
                      style={{ color: 'var(--signal-warn)' }}
                    >
                      · fallback
                    </span>
                  )}
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
