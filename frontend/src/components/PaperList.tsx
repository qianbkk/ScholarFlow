/**
 * PaperList — R10.5.54 论文编号列表
 *
 * 取代 QueryPanel 内的 paper list: 编号列表, 无 card, 2px 左侧 rule 仅选中态.
 * shift-click 第二篇 → CompareDrawer 打开.
 */
import { useStore, actions } from '../store/useStore';
import type { Paper } from '../types';

interface Props {
  papers: Paper[];
}

export function PaperList({ papers }: Props) {
  const selectedPaperId = useStore((s) => s.selectedPaperId);
  const selectedPaperIds = useStore((s) => s.selectedPaperIds);

  const onClick = (id: string, e: React.MouseEvent) => {
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      actions.selectPaper(id, true);
      if (selectedPaperIds.length >= 1) actions.openCompareDrawer();
    } else {
      actions.selectPaper(id, false);
    }
  };

  if (papers.length === 0) return null;

  return (
    <section style={{ marginTop: 48 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 12,
          paddingBottom: 8,
          borderBottom: '1px solid var(--sf-border)',
        }}
      >
        <h2 className="font-ui" style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>
          {papers.length} papers
        </h2>
        <span
          className="font-mono"
          style={{ fontSize: 11, color: 'var(--sf-muted)' }}
        >
          shift-click to compare
        </span>
      </div>

      <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {papers.map((p, i) => {
          const selected = selectedPaperId === p.paper_id;
          const inSelection = selectedPaperIds.includes(p.paper_id);
          return (
            <li
              key={p.paper_id}
              style={{
                position: 'relative',
                padding: '12px 0 12px 16px',
                borderBottom: '1px solid var(--sf-border)',
                cursor: 'pointer',
                transition: 'background-color 100ms ease',
                backgroundColor: selected ? 'var(--sf-surface-alt)' : 'transparent',
              }}
              onClick={(e) => onClick(p.paper_id, e)}
              onMouseEnter={(e) => {
                if (!selected) e.currentTarget.style.backgroundColor = 'var(--sf-surface)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = selected ? 'var(--sf-surface-alt)' : 'transparent';
              }}
            >
              {/* 2px left rule when selected */}
              {(selected || inSelection) && (
                <span
                  aria-hidden
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: 2,
                    backgroundColor: 'var(--sf-accent)',
                  }}
                />
              )}
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
                <span
                  className="font-mono"
                  style={{
                    fontSize: 11,
                    color: 'var(--sf-muted)',
                    minWidth: 28,
                  }}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    className="font-body"
                    style={{
                      fontSize: 15,
                      lineHeight: 1.4,
                      color: 'var(--sf-text)',
                      marginBottom: 4,
                    }}
                  >
                    {p.title}
                  </div>
                  <div
                    className="font-mono"
                    style={{
                      fontSize: 11,
                      color: 'var(--sf-muted)',
                      display: 'flex',
                      gap: 12,
                      flexWrap: 'wrap',
                    }}
                  >
                    <span>{p.year || '—'}</span>
                    <span>{(p.authors || []).slice(0, 3).join(', ')}{(p.authors?.length || 0) > 3 ? ' et al.' : ''}</span>
                    <span>{p.venue || '—'}</span>
                    <span>{p.citation_count || 0} cite</span>
                    <span>★{(p.final_score ?? 0).toFixed(1)}</span>
                    {p.is_fallback && (
                      <span style={{ color: 'var(--sf-accent)' }} title="fallback data">⚠ fallback</span>
                    )}
                  </div>
                </div>
                <a
                  href={p.url || '#'}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="font-ui"
                  style={{
                    fontSize: 11,
                    color: 'var(--sf-accent)',
                    textDecoration: 'none',
                    borderBottom: '1px solid transparent',
                    flexShrink: 0,
                  }}
                  title="Open paper"
                >
                  ↗
                </a>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}