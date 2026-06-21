/**
 * QueryInput — R10.5.54 Search 视图输入区
 *
 * textarea + provider/budget/iter/paperCount + Ask 按钮 + recent 内联展开列表.
 * 不再有 popover / formCollapsed / runtime mode radios (移去 Settings).
 *
 * R10.5.59: 加 paperCount [min, max] 双滑块 (3-30, 默认 5-10).
 */
import { useState, useRef, useEffect } from 'react';
import { useStore, actions } from '../store/useStore';
import { useT } from '../i18n';

interface Props {
  providers: Array<{ id: string; label: string; enabled: boolean; has_key: boolean }>;
}

export function QueryInput({ providers }: Props) {
  const query = useStore((s) => s.query);
  const loading = useStore((s) => s.loading);
  const recentSearches = useStore((s) => s.recentSearches);
  const user = useStore((s) => s.user);
  const hasApiKey = useStore((s) => s.hasApiKey);
  const runtimeMode = useStore((s) => s.runtimeMode);
  const t = useT();

  const [provider, setProvider] = useState<string>('minimax');
  const [budget, setBudget] = useState<number>(2.0);
  const [maxIter, setMaxIter] = useState<number>(3);
  // R10.5.59: paper count range — min 3, max 30, default 5-10.
  const [paperMin, setPaperMin] = useState<number>(5);
  const [paperMax, setPaperMax] = useState<number>(10);
  const [recentOpen, setRecentOpen] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    actions.search(query, budget, maxIter, provider, paperMin, paperMax);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      submit();
    }
  };

  const pickRecent = (q: string) => {
    actions.setQuery(q);
    setRecentOpen(false);
    textareaRef.current?.focus();
  };

  const providerList = providers.length > 0
    ? providers
    : [
        { id: 'minimax', label: 'minimax', enabled: true, has_key: true },
        { id: 'kimi', label: 'kimi', enabled: true, has_key: false },
        { id: 'glm', label: 'glm', enabled: true, has_key: false },
        { id: 'anthropic', label: 'anthropic', enabled: true, has_key: false },
      ];

  const needsAuth = !user && !hasApiKey && runtimeMode !== 'local';

  return (
    <div style={{ marginBottom: 32 }}>
      <textarea
        ref={textareaRef}
        value={query}
        onChange={(e) => actions.setQuery(e.target.value)}
        onKeyDown={onKey}
        placeholder={t('query.placeholder')}
        disabled={loading}
        aria-label={t('query.placeholder')}
        rows={3}
        className="font-body"
        style={{
          width: '100%',
          padding: '12px 14px',
          border: '1px solid var(--sf-border)',
          backgroundColor: 'var(--sf-bg)',
          color: 'var(--sf-text)',
          fontSize: 17,
          lineHeight: 1.5,
          borderRadius: 2,
          resize: 'vertical',
          fontFamily: 'inherit',
          outline: 'none',
          transition: 'border-color 100ms ease',
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--sf-accent)'; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--sf-border)'; }}
      />

      {/* Control row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          marginTop: 12,
          flexWrap: 'wrap',
        }}
      >
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="font-ui" style={{ fontSize: 12, color: 'var(--sf-muted)' }}>
            {t('query.provider')}
          </span>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={loading}
            className="font-ui sf-input"
            style={{ padding: '4px 8px', fontSize: 13 }}
          >
            {providerList.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="font-ui" style={{ fontSize: 12, color: 'var(--sf-muted)' }}>
            {t('query.budget')}
          </span>
          <span className="font-mono" style={{ fontSize: 12, color: 'var(--sf-text)' }}>
            ${budget.toFixed(2)}
          </span>
          <input
            type="range"
            min={0.1}
            max={10}
            step={0.1}
            value={budget}
            onChange={(e) => setBudget(parseFloat(e.target.value))}
            disabled={loading}
            style={{ accentColor: 'var(--sf-accent)', width: 100 }}
            aria-label={t('query.budget')}
          />
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="font-ui" style={{ fontSize: 12, color: 'var(--sf-muted)' }}>
            {t('query.iter')}
          </span>
          <span className="font-mono" style={{ fontSize: 12, color: 'var(--sf-text)' }}>
            {maxIter}
          </span>
          <input
            type="range"
            min={1}
            max={5}
            step={1}
            value={maxIter}
            onChange={(e) => setMaxIter(parseInt(e.target.value, 10))}
            disabled={loading}
            style={{ accentColor: 'var(--sf-accent)', width: 60 }}
            aria-label={t('query.iter')}
          />
        </label>

        {/* R10.5.59: paper count dual-range slider (min-max) 3..30 default 5-10 */}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="font-ui" style={{ fontSize: 12, color: 'var(--sf-muted)' }}>
            {t('query.papers')}
          </span>
          <span className="font-mono" style={{ fontSize: 12, color: 'var(--sf-text)', minWidth: 56 }}>
            {paperMin}–{paperMax}
          </span>
          <input
            type="range"
            min={3}
            max={30}
            step={1}
            value={paperMin}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              setPaperMin(Math.min(v, paperMax));
            }}
            disabled={loading}
            style={{ accentColor: 'var(--sf-accent)', width: 56 }}
            aria-label={t('query.papersMin')}
            data-testid="paper-min-slider"
          />
          <input
            type="range"
            min={3}
            max={30}
            step={1}
            value={paperMax}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              setPaperMax(Math.max(v, paperMin));
            }}
            disabled={loading}
            style={{ accentColor: 'var(--sf-accent)', width: 56 }}
            aria-label={t('query.papersMax')}
            data-testid="paper-max-slider"
          />
        </label>

        <div style={{ flex: 1 }} />

        {loading ? (
          <button
            type="button"
            onClick={actions.cancelSearch}
            className="sf-btn font-ui"
            data-testid="cancel-btn"
          >
            {t('query.cancel')}
          </button>
        ) : needsAuth ? (
          <button
            type="button"
            onClick={actions.openAuthDialog}
            className="sf-btn sf-btn-primary font-ui"
            data-testid="signin-btn"
          >
            {t('query.signin')}
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!query.trim()}
            className="sf-btn sf-btn-primary font-ui"
            data-testid="ask-btn"
          >
            {t('query.ask')}
          </button>
        )}
      </div>

      {/* Recent inline list */}
      {recentSearches.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button
            type="button"
            onClick={() => setRecentOpen(!recentOpen)}
            className="font-ui"
            aria-expanded={recentOpen}
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              fontSize: 12,
              color: 'var(--sf-muted)',
            }}
          >
            {t('query.recent', { n: recentSearches.length })} {recentOpen ? '▾' : '▸'}
          </button>
          {recentOpen && (
            <ul style={{ listStyle: 'none', padding: 0, margin: '8px 0 0' }}>
              {recentSearches.map((r, i) => (
                <li
                  key={`${r.query}-${r.ts}-${i}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '6px 0',
                    borderTop: i > 0 ? '1px solid var(--sf-border)' : 'none',
                  }}
                >
                  <span
                    className="font-mono"
                    style={{
                      fontSize: 10,
                      color: r.source === 'real' ? 'var(--sf-accent)' : 'var(--sf-muted)',
                      width: 14,
                    }}
                    title={
                      r.source === 'real'
                        ? t('history.sourceReal')
                        : r.source === 'local'
                        ? t('history.sourceLocal')
                        : t('history.sourceUnknown')
                    }
                  >
                    {r.source === 'real' ? 'R' : r.source === 'local' ? 'L' : '?'}
                  </span>
                  <button
                    type="button"
                    onClick={() => pickRecent(r.query)}
                    className="font-body"
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: 0,
                      cursor: 'pointer',
                      fontSize: 14,
                      color: 'var(--sf-text)',
                      textAlign: 'left',
                      flex: 1,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {r.query}
                  </button>
                  <span
                    className="font-mono"
                    style={{ fontSize: 10, color: 'var(--sf-muted)' }}
                  >
                    {r.ts > 0 ? new Date(r.ts).toLocaleString() : '—'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}