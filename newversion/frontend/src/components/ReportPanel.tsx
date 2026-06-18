// ReportPanel — rendered Markdown with inline citations and references.
// v3 styling: mono + sans only, no serif, headings are small caps in --ink-2.

import { useMemo, useEffect, useState } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { useStore } from '../hooks/useStore';
import type { Paper } from '../types';

function hydrate(md: string, papers: Paper[]): string {
  if (!md) return '';
  const raw = marked.parse(md, { async: false }) as string;
  const safe = DOMPurify.sanitize(raw);
  // [paper_id:<id>] -> <sup class="cite">[N]</sup>
  return safe.replace(/\[paper_id:([a-z0-9_]+)\]/g, (_whole, id: string) => {
    const idx = papers.findIndex((p) => p.paper_id === id);
    if (idx < 0) return _whole;
    return `<sup><a class="cite" href="#ref-${id}" data-id="${id}">${idx + 1}</a></sup>`;
  });
}

export function ReportPanel() {
  const { result } = useStore();
  const [html, setHtml] = useState('');

  const md = result?.report ?? '';
  const papers = result?.ranked_papers ?? [];

  useEffect(() => {
    setHtml(hydrate(md, papers));
  }, [md, papers]);

  const sortedPapers = useMemo(() => [...papers].sort((a, b) => b.final_score - a.final_score), [papers]);

  if (!result) {
    return (
      <div
        className="mono text-[11px] py-8 px-4"
        style={{ color: 'var(--ink-3)' }}
      >
        report will appear here after a search
      </div>
    );
  }

  return (
    <div className="px-5 py-4">
      <article className="sf-prose">
        <div dangerouslySetInnerHTML={{ __html: html }} />
      </article>
      {sortedPapers.length > 0 && (
        <section className="mt-8 pt-4 hairline-t">
          <div
            className="mono text-[10px] uppercase mb-3"
            style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
          >
            references
          </div>
          <ol className="m-0 p-0 list-none space-y-2">
            {sortedPapers.map((p, i) => (
              <li
                key={p.paper_id}
                id={`ref-${p.paper_id}`}
                className="flex items-baseline gap-2"
                style={{ fontSize: '12px' }}
              >
                <span
                  className="mono tnum shrink-0"
                  style={{ color: 'var(--ink-3)', minWidth: 22 }}
                >
                  {(i + 1).toString().padStart(2, '0')}
                </span>
                <div className="min-w-0">
                  <div
                    className="display"
                    style={{ color: 'var(--ink-1)', fontWeight: 500 }}
                  >
                    {p.title}
                  </div>
                  <div
                    className="mono text-[10px] mt-0.5"
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
      )}
    </div>
  );
}
