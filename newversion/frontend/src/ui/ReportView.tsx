// ReportView — the reading-first center column.
// Markdown with inline paper cards. Click a citation to expand the card
// inline. One card open at a time. Click outside to close.

import { useEffect, useMemo, useState, useRef } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { useStore } from '../hooks/useStore';
import { store } from '../state/store';
import { PaperFootnote } from './PaperFootnote';
import type { Paper } from '../types';

function buildIndex(papers: Paper[]): Map<string, { paper: Paper; index: number }> {
  const m = new Map<string, { paper: Paper; index: number }>();
  const sorted = [...papers].sort((a, b) => b.final_score - a.final_score);
  sorted.forEach((p, i) => m.set(p.paper_id, { paper: p, index: i + 1 }));
  return m;
}

export function ReportView() {
  const { result, expandedPaperId } = useStore();
  const [, setHtml] = useState('');
  const containerRef = useRef<HTMLDivElement | null>(null);

  const sortedPapers = useMemo(
    () => (result ? [...result.ranked_papers].sort((a, b) => b.final_score - a.final_score) : []),
    [result],
  );
  const lookup = useMemo(() => buildIndex(sortedPapers), [sortedPapers]);

  const markdown = result?.report ?? '';

  useEffect(() => {
    if (!markdown) {
      setHtml('');
      return;
    }
    const raw = marked.parse(markdown, { async: false }) as string;
    const safe = DOMPurify.sanitize(raw);
    // [paper_id:<id>] -> <sup><a class="cite" data-id="...">N</a></sup>
    const out = safe.replace(/\[paper_id:([a-z0-9_]+)\]/g, (_w, id: string) => {
      const entry = lookup.get(id);
      if (!entry) return _w;
      return `<sup><a class="cite" data-id="${id}" href="#ref-${id}">${entry.index}</a></sup>`;
    });
    setHtml(out);
  }, [markdown, lookup]);

  // Click delegation on the report: any .cite click expands that paper.
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.classList.contains('cite')) {
        e.preventDefault();
        const id = target.dataset.id;
        if (id) store.expandPaper(id);
        return;
      }
      // Click outside the footnote card -> close it
      const card = (e.target as HTMLElement).closest('aside.sfv4-footnote');
      if (!card && expandedPaperId) {
        store.expandPaper(null);
      }
    };
    root.addEventListener('click', onClick);
    return () => root.removeEventListener('click', onClick);
  }, [expandedPaperId]);

  if (!result) return null;

  const expanded = expandedPaperId ? lookup.get(expandedPaperId) : null;

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto"
      style={{ background: 'var(--base)' }}
    >
      <div
        className="mx-auto px-6 pt-12 pb-16"
        style={{ maxWidth: 'var(--read-max)' }}
      >
        <div
          className="mono text-[10px] uppercase mb-4"
          style={{ color: 'var(--ink-3)', letterSpacing: '0.22em' }}
        >
          report · iteration {result.iteration} · {result.elapsed_seconds.toFixed(1)}s · ${result.total_cost_usd.toFixed(4)} · {result.total_tokens.toLocaleString()} tok
        </div>

        <article className="sf-prose">
          <div dangerouslySetInnerHTML={{ __html: '' }} />
          <h1 style={{ fontSize: '1.85rem', marginBottom: '0.6em' }}>{result.query}</h1>
          <RenderMarkdown markdown={markdown} lookup={lookup} />
        </article>

        {expanded && (
          <div className="sfv4-footnote">
            <PaperFootnote
              paper={expanded.paper}
              index={expanded.index}
              onCompare={() => store.setOverlay('compare')}
            />
          </div>
        )}

        <section className="mt-16 pt-8" style={{ borderTop: '1px solid var(--rule)' }}>
          <div
            className="mono text-[10px] uppercase mb-5"
            style={{ color: 'var(--ink-3)', letterSpacing: '0.22em' }}
          >
            references
          </div>
          <ol className="m-0 p-0 list-none" style={{ display: 'grid', gap: 18 }}>
            {sortedPapers.map((p, i) => (
              <li
                key={p.paper_id}
                id={`ref-${p.paper_id}`}
                className="flex items-baseline gap-3"
                style={{ fontSize: '13px' }}
              >
                <span
                  className="mono tnum shrink-0"
                  style={{ color: 'var(--ink-3)', minWidth: 26 }}
                >
                  {(i + 1).toString().padStart(2, '0')}
                </span>
                <div className="min-w-0">
                  <button
                    type="button"
                    onClick={() => store.expandPaper(p.paper_id)}
                    className="display"
                    style={{
                      background: 'transparent',
                      border: 'none',
                      padding: 0,
                      cursor: 'pointer',
                      color: 'var(--ink-1)',
                      fontWeight: 500,
                      fontSize: '14px',
                      textAlign: 'left',
                    }}
                  >
                    {p.title}
                  </button>
                  <div
                    className="mono text-[10.5px] mt-1"
                    style={{ color: 'var(--ink-2)' }}
                  >
                    {p.authors.slice(0, 4).join(', ')}
                    {p.authors.length > 4 ? ` +${p.authors.length - 4}` : ''}
                    {' · '}
                    {p.year}
                    {p.venue ? ` · ${p.venue}` : ''}
                    {p.doi ? ` · ${p.doi}` : ''}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}

interface RMProps {
  markdown: string;
  lookup: Map<string, { paper: Paper; index: number }>;
}

function RenderMarkdown({ markdown, lookup }: RMProps) {
  const [html, setHtml] = useState('');
  useEffect(() => {
    if (!markdown) {
      setHtml('');
      return;
    }
    const raw = marked.parse(markdown, { async: false }) as string;
    const safe = DOMPurify.sanitize(raw);
    // Strip the leading H1 — we render it separately above.
    const stripped = safe.replace(/^\s*<h1[^>]*>.*?<\/h1>\s*/i, '');
    const out = stripped.replace(/\[paper_id:([a-z0-9_]+)\]/g, (_w, id: string) => {
      const entry = lookup.get(id);
      if (!entry) return _w;
      return `<sup><a class="cite" data-id="${id}" href="#ref-${id}">${entry.index}</a></sup>`;
    });
    setHtml(out);
  }, [markdown, lookup]);
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
