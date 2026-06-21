/**
 * SearchWorkspace — R10.5.59 Search view (概要模式)
 *
 * QueryInput + PipelineProgress + 概要卡 (SearchSummary) + PaperList.
 * 完整报告不在这里渲染 — 用户点 "查看完整报告" 跳到 Report tab.
 */
import { useEffect, useState } from 'react';
import { useStore, actions } from '../store/useStore';
import { QueryInput } from './QueryInput';
import { PaperList } from './PaperList';
import { PipelineProgress } from './PipelineProgress';
import { SearchSummary } from './SearchSummary';
import { useT } from '../i18n';
import { fetchProviders } from '../services/api';

export function SearchWorkspace() {
  const result = useStore((s) => s.result);
  const error = useStore((s) => s.error);
  const loading = useStore((s) => s.loading);
  const budgetExceeded = useStore((s) => s.budgetExceeded);
  const lastSubmittedQuery = useStore((s) => s.lastSubmittedQuery);
  const isDegraded = !!result?.is_degraded_response;
  const t = useT();

  const [providers, setProviders] = useState<
    Array<{ id: string; label: string; enabled: boolean; has_key: boolean }>
  >([]);

  useEffect(() => {
    fetchProviders()
      .then((res) => {
        if (res?.providers) {
          setProviders(
            res.providers.map((p: any) => ({
              id: p.id,
              label: p.label || p.id,
              enabled: p.enabled !== false,
              has_key: !!p.has_key,
            })),
          );
        }
      })
      .catch(() => { /* keep empty */ });
  }, []);

  const papers = result?.ranked_papers ?? [];

  return (
    <main
      id="view-search"
      role="tabpanel"
      aria-labelledby="tab-search"
      style={{
        maxWidth: 720,
        margin: '0 auto',
        padding: '48px 24px 96px',
      }}
    >
      <h1
        className="font-display"
        style={{
          fontSize: 36,
          lineHeight: 1.2,
          letterSpacing: '-0.02em',
          margin: '0 0 12px',
        }}
      >
        {t('search.title')}
      </h1>
      <p
        className="font-body"
        style={{
          fontSize: 16,
          color: 'var(--sf-muted)',
          margin: '0 0 32px',
        }}
      >
        {t('search.subtitle')}
      </p>

      <QueryInput providers={providers} />

      {/* PipelineProgress: 8 nodes + thinking log + evolution scrubber */}
      {(loading || result) && <PipelineProgress />}

      {/* R10.5.59: Search 概要卡 — 不渲染完整报告. 跳报告按钮在 Report tab. */}
      <SearchSummary />

      {/* Error footer */}
      {error && (
        <p
          className="font-body"
          style={{
            fontSize: 14,
            color: 'var(--sf-accent)',
            margin: '24px 0',
            padding: '12px 0',
            borderTop: '1px solid var(--sf-border)',
          }}
        >
          {error}
          {budgetExceeded && (
            <>
              {' · '}
              <button
                type="button"
                onClick={() => {
                  const newBudget = budgetExceeded.budget_usd * 1.5;
                  actions.search(
                    lastSubmittedQuery,
                    Math.min(20, newBudget),
                    3,
                    undefined,
                  );
                }}
                className="font-ui"
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  color: 'var(--sf-accent)',
                  cursor: 'pointer',
                  textDecoration: 'underline',
                  textUnderlineOffset: 2,
                }}
              >
                retry with ${(budgetExceeded.budget_usd * 1.5).toFixed(2)}
              </button>
            </>
          )}
        </p>
      )}

      {/* Degraded response caption */}
      {isDegraded && (
        <p
          className="font-body"
          style={{
            fontSize: 13,
            color: 'var(--sf-muted)',
            margin: '16px 0 0',
            padding: '8px 0',
            borderTop: '1px dashed var(--sf-border)',
          }}
        >
          ⚠ Part of this result is from fallback data ({result?.fallback_paper_count ?? 0} papers).
        </p>
      )}

      <PaperList papers={papers} />
    </main>
  );
}