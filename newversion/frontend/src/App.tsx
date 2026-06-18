// App shell — vertical stack: TopBar / PipelineStrip / CommandBar / 3 panels / CompareBar? / Footer.
// 3 panels are: ResultsPanel (left), ReportPanel (center), GraphPanel (right).

import { TopBar } from './components/TopBar';
import { PipelineStrip } from './components/PipelineStrip';
import { CommandBar } from './components/CommandBar';
import { ResultsPanel } from './components/ResultsPanel';
import { ReportPanel } from './components/ReportPanel';
import { GraphPanel } from './components/GraphPanel';
import { CompareBar } from './components/CompareBar';
import { Footer } from './components/Footer';
import { useStore } from './hooks/useStore';

function PanelHeader({ label, count }: { label: string; count?: number | string }) {
  return (
    <div
      className="hairline-b flex items-center justify-between px-3 h-7"
      style={{ background: 'var(--surface-1)' }}
    >
      <span
        className="mono text-[10px] uppercase"
        style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
      >
        {label}
      </span>
      {count !== undefined && (
        <span
          className="mono tnum text-[10px]"
          style={{ color: 'var(--ink-2)' }}
        >
          {count}
        </span>
      )}
    </div>
  );
}

export function App() {
  const { result } = useStore();
  const graph = result?.citation_graph;
  const papers = result?.ranked_papers ?? [];

  return (
    <div
      className="h-screen flex flex-col"
      style={{ background: 'var(--base)' }}
    >
      <TopBar />
      <PipelineStrip />
      <CommandBar />

      <div
        className="flex-1 grid overflow-hidden"
        style={{
          gridTemplateColumns: 'minmax(260px, 320px) minmax(0, 1fr) minmax(280px, 360px)',
          minHeight: 0,
        }}
      >
        <aside className="hairline-r flex flex-col overflow-hidden">
          <PanelHeader label="results" count={papers.length || undefined} />
          <div className="flex-1 overflow-y-auto">
            <ResultsPanel />
          </div>
        </aside>

        <main className="overflow-y-auto">
          {result && (
            <div
              className="px-6 pt-4 pb-2 hairline-b"
              style={{ background: 'var(--base)' }}
            >
              <div
                className="mono text-[10px] uppercase mb-1.5"
                style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
              >
                query
              </div>
              <h1
                className="display m-0"
                style={{
                  fontSize: '1.4rem',
                  fontWeight: 500,
                  letterSpacing: '-0.015em',
                  color: 'var(--ink-1)',
                }}
              >
                {result.query}
              </h1>
              <div
                className="mono text-[10px] mt-1.5 flex items-center gap-3"
                style={{ color: 'var(--ink-3)' }}
              >
                <span>iter {result.iteration}</span>
                <span style={{ color: 'var(--rule-strong)' }}>·</span>
                <span>{result.elapsed_seconds.toFixed(1)}s</span>
                <span style={{ color: 'var(--rule-strong)' }}>·</span>
                <span>${result.total_cost_usd.toFixed(4)}</span>
                <span style={{ color: 'var(--rule-strong)' }}>·</span>
                <span>{result.total_tokens.toLocaleString()} tok</span>
                {result.is_degraded && (
                  <>
                    <span style={{ color: 'var(--rule-strong)' }}>·</span>
                    <span style={{ color: 'var(--signal-warn)' }}>degraded</span>
                  </>
                )}
              </div>
            </div>
          )}
          <ReportPanel />
          <CompareBar />
        </main>

        <aside className="hairline-l flex flex-col overflow-hidden">
          <PanelHeader label="graph" count={graph ? `${graph.metadata.total_papers}n/${graph.metadata.total_links}e` : undefined} />
          <div className="flex-1 overflow-hidden">
            {graph ? <GraphPanel graph={graph} /> : (
              <div
                className="mono text-[11px] py-6 px-3"
                style={{ color: 'var(--ink-3)' }}
              >
                graph renders after search
              </div>
            )}
          </div>
        </aside>
      </div>

      <Footer />
    </div>
  );
}
