// App — state machine that picks the right view based on mode.
// Header / center / Footer. Overlays (graph, papers, compare) are fullscreen
// layers that take over the center when active.

import { useEffect } from 'react';
import { useStore } from './hooks/useStore';
import { store } from './state/store';
import { Header } from './ui/Header';
import { Footer } from './ui/Footer';
import { EmptyState } from './ui/EmptyState';
import { RunningState } from './ui/RunningState';
import { ReportView } from './ui/ReportView';
import { GraphOverlay } from './ui/GraphOverlay';
import { PapersDrawer } from './ui/PapersDrawer';
import { CompareOverlay } from './ui/CompareOverlay';

function Modal({ open, onClose, children, size }: { open: boolean; onClose: () => void; children: React.ReactNode; size?: 'full' | 'drawer' }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-30"
      style={{ background: 'var(--base)' }}
      role="dialog"
      aria-modal
    >
      {children}
    </div>
  );
}

function KeyboardShortcuts() {
  const { mode, overlay } = useStore();
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key === 'g' && mode === 'done' && !overlay) {
        e.preventDefault();
        store.setOverlay('graph');
      } else if (meta && e.key === 'p' && mode === 'done' && !overlay) {
        e.preventDefault();
        store.setOverlay('papers');
      } else if (e.key === 'Escape' && overlay) {
        e.preventDefault();
        store.setOverlay(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mode, overlay]);
  return null;
}

export function App() {
  const { mode, result, overlay } = useStore();

  let center: React.ReactNode;
  if (mode === 'empty') center = <EmptyState />;
  else if (mode === 'running') center = <RunningState />;
  else center = <ReportView />;

  return (
    <div
      className="h-screen flex flex-col"
      style={{ background: 'var(--base)' }}
    >
      <KeyboardShortcuts />
      <Header />
      <div className="flex-1 overflow-hidden">{center}</div>
      <Footer />

      <Modal open={overlay === 'graph' && !!result} onClose={() => store.setOverlay(null)} size="full">
        <div className="flex flex-col h-full">
          <div
            className="hairline-b flex items-center justify-between px-6 h-12 shrink-0"
            style={{ background: 'var(--base)' }}
          >
            <div className="flex items-baseline gap-3">
              <span
                className="mono text-[10px] uppercase"
                style={{ color: 'var(--ink-3)', letterSpacing: '0.22em' }}
              >
                graph
              </span>
              {result && (
                <span className="mono tnum text-[11px]" style={{ color: 'var(--ink-1)' }}>
                  {result.citation_graph.metadata.total_papers} nodes · {result.citation_graph.metadata.total_links} edges
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => store.setOverlay(null)}
              className="mono text-[10px] uppercase"
              style={{
                background: 'transparent',
                color: 'var(--ink-2)',
                border: '1px solid var(--rule-strong)',
                padding: '4px 10px',
                letterSpacing: '0.14em',
              }}
            >
              esc close
            </button>
          </div>
          <div
            className="flex-1 flex items-center justify-center"
            style={{ background: 'var(--base)' }}
          >
            {result && <GraphOverlay graph={result.citation_graph} />}
          </div>
          <div
            className="hairline-t px-6 py-3 mono text-[10px] flex items-center justify-between"
            style={{ color: 'var(--ink-3)' }}
          >
            <span>click a node to open that paper · drag to move · scroll to zoom</span>
            <span>viridis by year</span>
          </div>
        </div>
      </Modal>

      <Modal open={overlay === 'papers' && !!result} onClose={() => store.setOverlay(null)} size="drawer">
        <div
          className="fixed inset-y-0 right-0 w-[400px] hairline-l"
          style={{ background: 'var(--surface-1)' }}
        >
          <PapersDrawer />
        </div>
      </Modal>

      <Modal open={overlay === 'compare' && !!result} onClose={() => store.setOverlay(null)} size="full">
        <CompareOverlay />
      </Modal>
    </div>
  );
}
