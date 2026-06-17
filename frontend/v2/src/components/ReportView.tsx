// ReportView — rendered Markdown.
// Uses marked + DOMPurify. The report is the hero of the center column.

import { useEffect, useState, useMemo } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import type { Paper } from '../types/domain';

interface Props {
  markdown: string;
  papers: Paper[];
}

function buildCitationLookup(papers: Paper[]): Map<string, Paper> {
  const m = new Map<string, Paper>();
  for (const p of papers) m.set(p.paper_id, p);
  return m;
}

export function ReportView({ markdown, papers }: Props) {
  const lookup = useMemo(() => buildCitationLookup(papers), [papers]);

  const html = useMemo(() => {
    if (!markdown) return '';
    const raw = marked.parse(markdown, { async: false }) as string;
    return DOMPurify.sanitize(raw, {
      ADD_ATTR: ['target', 'rel'],
    });
  }, [markdown]);

  // Hydrate inline citations [paper_id] -> <sup><a class="cite" href="#p:{id}">{n}</a></sup>
  const [hydrated, setHydrated] = useState(html);
  useEffect(() => {
    if (!html) {
      setHydrated('');
      return;
    }
    // Number papers by ranked order so citations show 1, 2, 3 ... (stable across renders).
    const sorted = [...papers].sort((a, b) => b.final_score - a.final_score);
    const indexById = new Map(sorted.map((p, i) => [p.paper_id, i + 1]));

    let out = html;
    // Match [paper_id] and [paper_id|note] patterns.
    out = out.replace(/\[([a-z0-9_]+)(?:\|[^\]]*)?\]/gi, (whole, id: string) => {
      const n = indexById.get(id);
      if (n === undefined) return whole;
      return `<sup><a class="cite" href="#p-${id}" data-paper-id="${id}">${n}</a></sup>`;
    });
    setHydrated(out);
  }, [html, papers]);

  if (!markdown) {
    return (
      <div
        className="display text-[15px] italic py-12 px-2"
        style={{ color: 'var(--ink-3)' }}
      >
        Run a search to see the synthesized report here.
      </div>
    );
  }

  return (
    <article className="sf-prose">
      <div dangerouslySetInnerHTML={{ __html: hydrated }} />
      {papers.length > 0 && (
        <section
          className="mt-12 pt-6 hairline-t"
          style={{ borderColor: 'var(--rule)' }}
        >
          <h2
            className="mono text-[11px] uppercase tracking-[0.18em] m-0 mb-4"
            style={{ color: 'var(--ink-3)', fontFamily: '"JetBrains Mono", monospace', fontWeight: 500 }}
          >
            References
          </h2>
          <ol className="m-0 p-0 list-none space-y-3">
            {[...papers]
              .sort((a, b) => b.final_score - a.final_score)
              .map((p, i) => (
                <li
                  key={p.paper_id}
                  id={`p-${p.paper_id}`}
                  className="flex items-baseline gap-3"
                  style={{ fontSize: '13px' }}
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
                      style={{ color: 'var(--ink)', fontWeight: 500 }}
                    >
                      {p.title}
                    </div>
                    <div
                      className="mono text-[11px] mt-0.5"
                      style={{ color: 'var(--ink-2)' }}
                    >
                      {p.authors.slice(0, 4).join(', ')}
                      {p.authors.length > 4 ? ` +${p.authors.length - 4}` : ''} · {p.year}
                      {p.venue ? ` · ${p.venue}` : ''}
                      {p.doi ? ` · doi:${p.doi}` : ''}
                    </div>
                    {p.url && (
                      <a
                        href={p.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="mono text-[11px]"
                        style={{ color: 'var(--accent)' }}
                      >
                        {p.url}
                      </a>
                    )}
                  </div>
                </li>
              ))}
          </ol>
        </section>
      )}
    </article>
  );
}
