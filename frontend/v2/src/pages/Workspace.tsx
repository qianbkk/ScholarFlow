// Workspace — the main app shell.
// Three regions: left rail (query + papers), center (report), right rail (graph).
// Single-region dominance: report owns the center with max 75ch reading width;
// rails are scoped to fixed widths and scroll independently.

import { useState } from 'react';
import { useSearch } from '../contexts/SearchContext';
import { QueryInput } from '../components/QueryInput';
import { PaperList } from '../components/PaperList';
import { ReportView } from '../components/ReportView';
import { CitationGraph } from '../components/CitationGraph';
import { CompareDrawer } from '../components/CompareDrawer';
import { StatusBar } from '../components/StatusBar';

export function Workspace() {
  const { state } = useSearch();
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const result = state.result;

  return (
    <div className="min-h-screen flex flex-col">
      <StatusBar />

      <div
        className="flex-1 grid"
        style={{
          gridTemplateColumns: 'minmax(280px, 360px) minmax(0, 1fr) minmax(320px, 420px)',
          minHeight: 0,
        }}
      >
        {/* Left rail: query + paper list */}
        <aside className="hairline-r flex flex-col overflow-hidden">
          <div className="px-5 py-5 hairline-b">
            <QueryInput />
          </div>
          <div className="px-5 pt-4 pb-2 flex items-baseline justify-between">
            <span
              className="mono text-[11px] uppercase tracking-[0.18em]"
              style={{ color: 'var(--ink-3)' }}
            >
              Papers
            </span>
            <span
              className="mono tnum text-[11px]"
              style={{ color: 'var(--ink-2)' }}
            >
              {result?.ranked_papers.length ?? 0}
            </span>
          </div>
          <div className="flex-1 overflow-y-auto">
            <PaperList
              papers={result?.ranked_papers ?? []}
              onHoverPaper={setHoveredId}
              activeId={hoveredId}
            />
          </div>
        </aside>

        {/* Center: report */}
        <main className="overflow-y-auto">
          <div className="mx-auto px-10 py-10" style={{ maxWidth: 820 }}>
            {result && (
              <header className="mb-8">
                <span
                  className="mono text-[10px] uppercase tracking-[0.2em] block mb-2"
                  style={{ color: 'var(--ink-3)' }}
                >
                  Report
                </span>
                <h1
                  className="display m-0"
                  style={{
                    fontSize: '1.75rem',
                    fontWeight: 500,
                    letterSpacing: '-0.025em',
                    color: 'var(--ink)',
                  }}
                >
                  {state.query}
                </h1>
                <div
                  className="mono text-[11px] mt-3 flex items-center gap-3"
                  style={{ color: 'var(--ink-3)' }}
                >
                  <span>iteration {result.iteration}</span>
                  <span style={{ color: 'var(--rule-strong)' }}>·</span>
                  <span>{result.elapsed_seconds.toFixed(1)}s</span>
                  <span style={{ color: 'var(--rule-strong)' }}>·</span>
                  <span>${result.total_cost_usd.toFixed(4)}</span>
                  {result.is_degraded_response && (
                    <>
                      <span style={{ color: 'var(--rule-strong)' }}>·</span>
                      <span style={{ color: 'var(--signal-warn)' }}>
                        degraded ({result.fallback_paper_count} fallback)
                      </span>
                    </>
                  )}
                </div>
              </header>
            )}
            <ReportView markdown={result?.report ?? ''} papers={result?.ranked_papers ?? []} />
            {result && <CompareDrawer />}
          </div>
        </main>

        {/* Right rail: citation graph */}
        <aside className="hairline-l flex flex-col overflow-hidden">
          <div className="px-5 py-4 hairline-b flex items-baseline justify-between">
            <span
              className="mono text-[11px] uppercase tracking-[0.18em]"
              style={{ color: 'var(--ink-3)' }}
            >
              Citation graph
            </span>
            <span
              className="mono tnum text-[11px]"
              style={{ color: 'var(--ink-2)' }}
            >
              {result?.citation_graph.metadata.total_papers ?? 0} nodes
            </span>
          </div>
          <div className="flex-1 overflow-hidden">
            {result ? (
              <CitationGraph
                graph={result.citation_graph}
                hoveredId={hoveredId}
                onHoverNode={setHoveredId}
              />
            ) : (
              <div
                className="mono text-[11px] py-12 px-5"
                style={{ color: 'var(--ink-3)' }}
              >
                Graph will render once the search finishes.
              </div>
            )}
          </div>
          {result && (
            <div
              className="px-5 py-3 hairline-t mono text-[11px]"
              style={{ color: 'var(--ink-3)' }}
            >
              <span style={{ color: 'var(--ink-2)' }}>
                {result.citation_graph.metadata.community_count ?? '—'} communities
              </span>
              <span className="mx-2" style={{ color: 'var(--rule-strong)' }}>
                ·
              </span>
              <span>
                {result.citation_graph.metadata.link_type_counts?.cites ?? 0} cite links
              </span>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
