/**
 * SearchWorkspace — R10.5.59 Search view (概要模式)
 *
 * QueryInput + PipelineProgress + 概要卡 (SearchSummary) + PaperFilterBar + PaperList.
 * 完整报告不在这里渲染 — 用户点 "查看完整报告" 跳到 Report tab.
 *
 * R10.5.93 (升级 3): 加 PaperFilterBar, 按 stance / study_type 过滤 papers.
 */
import { useEffect, useMemo, useState } from 'react';
import { useStore, actions } from '../store/useStore';
import { QueryInput } from './QueryInput';
import { PaperList } from './PaperList';
import { PaperFilterBar, type PaperFilters } from './PaperFilterBar';
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

  // R10.5.93: filter state. 切换 query 时重置.
  const [filters, setFilters] = useState<PaperFilters>({ stance: null, studyType: null });
  const lastQueryRef = useMemo(() => result?.citation_graph?.metadata?.query ?? '', [result]);
  useEffect(() => {
    // 新查询时重置过滤
    setFilters({ stance: null, studyType: null });
  }, [lastQueryRef]);

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

  const allPapers = result?.ranked_papers ?? [];
  // R10.5.93: 按 filter 过滤 papers
  const papers = useMemo(() => {
    if (!filters.stance && !filters.studyType) return allPapers;
    return allPapers.filter((p) => {
      if (filters.stance && (p.stance || 'unsure') !== filters.stance) return false;
      if (filters.studyType && (p.study_type || 'other') !== filters.studyType) return false;
      return true;
    });
  }, [allPapers, filters]);

  const hiddenCount = allPapers.length - papers.length;

  return (
    <main
      id="view-search"
      role="tabpanel"
      aria-labelledby="tab-search"
      style={{
        maxWidth: 760,
        margin: '0 auto',
        padding: '56px 32px 96px',
      }}
    >
      <header style={{ marginBottom: 40 }}>
        <h1
          className="font-display"
          style={{
            fontSize: 38,
            lineHeight: 1.15,
            letterSpacing: '-0.025em',
            margin: '0 0 10px',
            color: 'var(--sf-text)',
          }}
        >
          {t('search.title')}
        </h1>
        <p
          className="font-body"
          style={{
            fontSize: 15,
            lineHeight: 1.55,
            color: 'var(--sf-muted)',
            margin: 0,
            maxWidth: 600,
          }}
        >
          {t('search.subtitle')}
        </p>
      </header>

      <QueryInput providers={providers} />

      {/* PipelineProgress: 8 nodes + thinking log + evolution scrubber */}
      {(loading || result) && (
        <div style={{ marginTop: 32 }}>
          <PipelineProgress />
        </div>
      )}

      {/* R10.5.59: Search 概要卡 — 不渲染完整报告. 跳报告按钮在 Report tab. */}
      <SearchSummary />

      {/* Error footer */}
      {error && (
        <div
          className="font-body sf-fade-in"
          role="alert"
          style={{
            fontSize: 14,
            lineHeight: 1.5,
            color: 'var(--sf-accent)',
            margin: '24px 0',
            padding: '12px 16px',
            border: '1px solid var(--sf-accent)',
            borderRadius: 2,
            backgroundColor: 'oklch(96% 0.03 40 / 0.4)',
          }}
          data-testid="search-error"
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
        </div>
      )}

      {/* Degraded response caption */}
      {isDegraded && (
        <p
          className="font-body sf-fade-in"
          role="status"
          style={{
            fontSize: 13,
            lineHeight: 1.5,
            color: 'var(--sf-muted)',
            margin: '20px 0 0',
            padding: '10px 14px',
            border: '1px dashed var(--sf-border)',
            borderRadius: 2,
            backgroundColor: 'var(--sf-surface-alt)',
          }}
        >
          ⚠ Part of this result is from fallback data ({result?.fallback_paper_count ?? 0} papers).
        </p>
      )}

      {/* R10.5.93 (升级 3): stance + study_type 过滤栏 (Consensus / Elicit 风格) */}
      {allPapers.length > 0 && (
        <PaperFilterBar
          papers={allPapers}
          filters={filters}
          onChange={setFilters}
        />
      )}

      {hiddenCount > 0 && (
        <p
          className="font-mono"
          style={{
            fontSize: 10,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            color: 'var(--sf-muted)',
            margin: '8px 0 0',
          }}
          data-testid="filter-hidden-count"
        >
          · 已隐藏 {hiddenCount} 篇 (不符合当前过滤)
        </p>
      )}

      <PaperList papers={papers} />
    </main>
  );
}