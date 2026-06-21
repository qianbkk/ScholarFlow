/**
 * HistoryView — R10.5.59 完整 i18n + history list
 */
import { useStore, actions } from '../store/useStore';
import { useT } from '../i18n';

export function HistoryView() {
  const recent = useStore((s) => s.recentSearches);
  const result = useStore((s) => s.result);
  const lastQuery = useStore((s) => s.lastQuery);
  const t = useT();

  const hasResultFor = (q: string) => !!result && lastQuery === q;

  return (
    <main
      id="view-history"
      role="tabpanel"
      aria-labelledby="tab-history"
      style={{
        maxWidth: 760,
        margin: '0 auto',
        padding: '56px 32px 96px',
      }}
    >
      <header style={{ marginBottom: 32 }}>
        <h1
          className="font-display"
          style={{
            fontSize: 32,
            letterSpacing: '-0.02em',
            margin: '0 0 8px',
          }}
        >
          {t('history.title')}
        </h1>
        <p
          className="font-body"
          style={{
            fontSize: 14,
            color: 'var(--sf-muted)',
            margin: 0,
          }}
        >
          {recent.length} 条 · sessionStorage 持久化
        </p>
      </header>

      {recent.length === 0 ? (
        <div
          className="sf-fade-in"
          style={{
            padding: '64px 24px',
            textAlign: 'center',
            color: 'var(--sf-muted)',
            border: '1px dashed var(--sf-border)',
            borderRadius: 2,
            backgroundColor: 'var(--sf-surface)',
          }}
        >
          <p
            className="font-display"
            style={{ fontSize: 18, fontStyle: 'italic', margin: '0 0 8px', color: 'var(--sf-text)' }}
          >
            {t('history.emptyTitle')}
          </p>
          <p className="font-body" style={{ fontSize: 13, margin: 0 }}>
            {t('history.empty')}
          </p>
        </div>
      ) : (
        <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {recent.map((r, i) => {
            const sourceLabel =
              r.source === 'real' ? 'R' : r.source === 'local' ? 'L' : '?';
            const sourceColor =
              r.source === 'real'
                ? 'var(--sf-accent)'
                : 'var(--sf-muted)';
            const sourceName =
              r.source === 'real'
                ? t('history.sourceReal')
                : r.source === 'local'
                ? t('history.sourceLocal')
                : t('history.sourceUnknown');
            return (
              <li
                key={`${r.query}-${r.ts}-${i}`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  padding: '14px 0',
                  borderBottom: '1px solid var(--sf-border)',
                }}
              >
                <span
                  className="font-mono"
                  style={{
                    fontSize: 12,
                    color: 'var(--sf-muted)',
                    width: 28,
                  }}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    className="font-body"
                    style={{
                      fontSize: 15,
                      color: 'var(--sf-text)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      marginBottom: 4,
                    }}
                  >
                    {r.query}
                  </div>
                  <div
                    className="font-mono"
                    style={{
                      fontSize: 11,
                      color: 'var(--sf-muted)',
                      display: 'flex',
                      gap: 12,
                    }}
                  >
                    <span>{r.ts > 0 ? new Date(r.ts).toLocaleString() : '—'}</span>
                    <span style={{ color: sourceColor }}>
                      {sourceLabel} ({sourceName})
                    </span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {hasResultFor(r.query) && (
                    <button
                      type="button"
                      onClick={() => actions.setView('report')}
                      className="sf-btn font-ui"
                      style={{ padding: '4px 10px', fontSize: 12 }}
                    >
                      {t('history.open')}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      actions.setQuery(r.query);
                      actions.setView('search');
                    }}
                    className="sf-btn font-ui"
                    style={{ padding: '4px 10px', fontSize: 12 }}
                  >
                    {t('history.rerun')}
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </main>
  );
}