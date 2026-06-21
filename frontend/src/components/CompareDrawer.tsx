/**
 * CompareDrawer — R10.5.54 简化版: paper A vs paper B 元数据对比
 *
 * 取代旧 618 行 CompareDrawer: 不再有 critic reviews / 4-tab internal /
 * quality_score / confidence_score — 后端 critic agent 是 stub 不产可操作结果.
 */
import { useStore, actions } from '../store/useStore';
import type { Paper } from '../types';

export function CompareDrawer() {
  const open = useStore((s) => s.compareDrawerOpen);
  const ids = useStore((s) => s.selectedPaperIds);
  const result = useStore((s) => s.result);

  if (!open || ids.length < 2 || !result?.ranked_papers) return null;

  const papers: Paper[] = ids
    .map((id) => result.ranked_papers?.find((p) => p.paper_id === id))
    .filter((p): p is Paper => !!p);

  if (papers.length < 2) return null;

  const [A, B] = papers;

  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-label="论文对比"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 90,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      <div
        onClick={actions.closeCompareDrawer}
        style={{
          position: 'absolute',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.3)',
        }}
      />
      <aside
        className="sf-fade-in"
        style={{
          position: 'relative',
          width: 560,
          maxWidth: '100vw',
          height: '100vh',
          backgroundColor: 'var(--sf-bg)',
          borderLeft: '1px solid var(--sf-border)',
          overflowY: 'auto',
          padding: 24,
        }}
      >
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 24,
            paddingBottom: 12,
            borderBottom: '1px solid var(--sf-border)',
          }}
        >
          <h1 className="font-display" style={{ fontSize: 22, letterSpacing: '-0.02em', margin: 0 }}>
            Compare
          </h1>
          <button
            type="button"
            onClick={actions.closeCompareDrawer}
            className="sf-btn font-ui"
            style={{ padding: '4px 10px', fontSize: 12 }}
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <CompareTable A={A} B={B} />
      </aside>
    </div>
  );
}

function CompareTable({ A, B }: { A: Paper; B: Paper }) {
  return (
    <div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 16,
          marginBottom: 16,
          paddingBottom: 12,
          borderBottom: '1px solid var(--sf-border)',
        }}
      >
        <div>
          <span
            className="font-mono"
            style={{ fontSize: 11, color: 'var(--sf-muted)', marginRight: 8 }}
          >
            A
          </span>
          <span className="font-body" style={{ fontSize: 14, fontWeight: 600 }}>
            {A.title}
          </span>
        </div>
        <div>
          <span
            className="font-mono"
            style={{ fontSize: 11, color: 'var(--sf-muted)', marginRight: 8 }}
          >
            B
          </span>
          <span className="font-body" style={{ fontSize: 14, fontWeight: 600 }}>
            {B.title}
          </span>
        </div>
      </div>

      <table className="sf-table" style={{ fontSize: 13 }}>
        <tbody>
          <tr><th>Year</th><td>{A.year || '—'}</td><td>{B.year || '—'}</td></tr>
          <tr><th>Venue</th><td>{A.venue || '—'}</td><td>{B.venue || '—'}</td></tr>
          <tr>
            <th>Authors</th>
            <td>{(A.authors || []).slice(0, 4).join(', ')}{(A.authors?.length || 0) > 4 ? ' et al.' : ''}</td>
            <td>{(B.authors || []).slice(0, 4).join(', ')}{(B.authors?.length || 0) > 4 ? ' et al.' : ''}</td>
          </tr>
          <tr><th>Citations</th><td>{A.citation_count ?? 0}</td><td>{B.citation_count ?? 0}</td></tr>
          <tr><th>Final score</th><td>★{(A.final_score ?? 0).toFixed(1)}</td><td>★{(B.final_score ?? 0).toFixed(1)}</td></tr>
          <tr><th>Relevance</th><td>{(A.relevance_score ?? 0).toFixed(2)}</td><td>{(B.relevance_score ?? 0).toFixed(2)}</td></tr>
          <tr><th>Authority</th><td>{(A.authority_score ?? 0).toFixed(2)}</td><td>{(B.authority_score ?? 0).toFixed(2)}</td></tr>
          <tr><th>Source</th><td>{A.source || '—'}</td><td>{B.source || '—'}</td></tr>
        </tbody>
      </table>

      <h3 className="font-ui" style={{ fontSize: 13, fontWeight: 600, color: 'var(--sf-muted)', marginTop: 24, marginBottom: 8 }}>
        Abstract A
      </h3>
      <p className="font-body" style={{ fontSize: 13, lineHeight: 1.5, margin: '0 0 16px' }}>
        {A.abstract || '—'}
      </p>

      <h3 className="font-ui" style={{ fontSize: 13, fontWeight: 600, color: 'var(--sf-muted)', marginTop: 16, marginBottom: 8 }}>
        Abstract B
      </h3>
      <p className="font-body" style={{ fontSize: 13, lineHeight: 1.5, margin: 0 }}>
        {B.abstract || '—'}
      </p>
    </div>
  );
}