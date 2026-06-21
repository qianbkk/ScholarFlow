/**
 * ReportView — R10.5.59 markdown 报告渲染 (Report tab)
 *
 * R10.5.59: 报告页内容居中显示 (max-width + margin auto). 同时:
 *   - 加 "← 返回 Search" 跳回 Search tab 的链接 (SearchSummary 跳报告入口对应)
 *   - i18n 全文翻译
 *   - 不再渲染 GraphSlot (Report tab 只看报告, Graph tab 独立看图)
 */
import { useMemo } from 'react';
import { useStore, actions } from '../store/useStore';
import type { Paper } from '../types';
import { useT } from '../i18n';
import DOMPurify from 'dompurify';
import { marked } from 'marked';

interface Props {
  query?: string;
  graphSlot?: React.ReactNode;
}

export function ReportView({ query: queryProp, graphSlot }: Props) {
  const result = useStore((s) => s.result);
  const selectedPaperId = useStore((s) => s.selectedPaperId);
  const t = useT();

  const query = queryProp ?? result?.citation_graph?.metadata?.query ?? '';

  const html = useMemo(() => {
    const md = result?.report;
    if (!md) return '';
    const dirty = marked.parse(md, { async: false, gfm: true, breaks: false }) as string;
    return DOMPurify.sanitize(dirty, {
      ALLOWED_TAGS: ['h1','h2','h3','h4','p','ul','ol','li','strong','em','code','pre','blockquote','a','hr','table','thead','tbody','tr','th','td','br','span'],
      ALLOWED_ATTR: ['href','title','rel','target','data-paper-id'],
    });
  }, [result?.report]);

  const anchoredIds = useMemo(() => {
    const re = /\[(\d+)\]/g;
    const ids = new Set<string>();
    if (!result?.report || !result.ranked_papers) return [];
    let m: RegExpExecArray | null;
    while ((m = re.exec(result.report)) !== null) {
      const idx = parseInt(m[1], 10) - 1;
      if (idx >= 0 && idx < result.ranked_papers.length) {
        ids.add(result.ranked_papers[idx].paper_id);
      }
    }
    return Array.from(ids);
  }, [result?.report, result?.ranked_papers]);

  if (!result) {
    return (
      <main
        id="view-report"
        role="tabpanel"
        aria-labelledby="tab-report"
        style={{
          maxWidth: 720,
          margin: '0 auto',
          padding: '64px 24px 96px',
          textAlign: 'center',
        }}
      >
        <p className="font-body" style={{ color: 'var(--sf-muted)', fontSize: 14 }}>
          {t('report.empty')}
        </p>
        <button
          type="button"
          onClick={() => actions.setView('search')}
          className="sf-btn font-ui"
          style={{ marginTop: 24 }}
        >
          ← {t('report.goSearch')}
        </button>
      </main>
    );
  }

  const anchoredPapers: Paper[] = anchoredIds
    .map((id) => result.ranked_papers?.find((p) => p.paper_id === id))
    .filter((p): p is Paper => !!p);

  const downloadFile = (content: string, filename: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <main
      id="view-report"
      role="tabpanel"
      aria-labelledby="tab-report"
      style={{
        maxWidth: 720,
        margin: '0 auto',
        padding: '48px 24px 96px',
      }}
      data-testid="report-view"
    >
      {/* Back-to-search + meta header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
        }}
      >
        <button
          type="button"
          onClick={() => actions.setView('search')}
          className="font-mono"
          style={{
            background: 'none',
            border: 'none',
            padding: 0,
            fontSize: 11,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: 'var(--sf-muted)',
            cursor: 'pointer',
          }}
        >
          ← {t('report.backSearch')}
        </button>
        <nav
          aria-label={t('report.download')}
          style={{ display: 'flex', gap: 12, fontSize: 12 }}
        >
          {result.bibtex && (
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                downloadFile(result.bibtex!, 'scholarflow.bib', 'application/x-bibtex');
              }}
              className="font-mono"
              style={{ color: 'var(--sf-accent)', textDecoration: 'none' }}
              download="scholarflow.bib"
            >
              ↓ .bib
            </a>
          )}
          {result.ris && (
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                downloadFile(result.ris!, 'scholarflow.ris', 'application/x-research-info-systems');
              }}
              className="font-mono"
              style={{ color: 'var(--sf-accent)', textDecoration: 'none' }}
              download="scholarflow.ris"
            >
              ↓ .ris
            </a>
          )}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              downloadFile(result.report || '', 'scholarflow-report.md', 'text/markdown');
            }}
            className="font-mono"
            style={{ color: 'var(--sf-accent)', textDecoration: 'none' }}
            download="scholarflow-report.md"
          >
            ↓ .md
          </a>
        </nav>
      </div>

      <header
        style={{
          marginBottom: 24,
          paddingBottom: 16,
          borderBottom: '1px solid var(--sf-border)',
        }}
      >
        <h1
          className="font-display"
          style={{
            fontSize: 30,
            lineHeight: 1.2,
            letterSpacing: '-0.02em',
            fontStyle: 'italic',
            margin: 0,
          }}
        >
          {query || t('report.title')}
        </h1>
      </header>

      {/* Loading skeleton */}
      {!result.report && (
        <div className="report-body">
          {[60, 90, 75, 100, 50, 85, 70].map((w, i) => (
            <div
              key={i}
              style={{
                height: 14,
                width: `${w}%`,
                margin: '8px 0',
                background: 'var(--sf-border)',
                borderRadius: 2,
              }}
            />
          ))}
        </div>
      )}

      {/* Rendered report */}
      {result.report && (
        <div
          className="report-body"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )}

      {/* Graph slot (Report tab 注入) */}
      {graphSlot}

      {/* Anchored papers */}
      {anchoredPapers.length > 0 && (
        <section style={{ marginTop: 48 }}>
          <h3
            className="font-ui"
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--sf-muted)',
              margin: '0 0 12px',
              paddingBottom: 8,
              borderBottom: '1px solid var(--sf-border)',
            }}
          >
            {t('report.anchored', { n: anchoredPapers.length })}
          </h3>
          <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {anchoredPapers.map((p, i) => {
              const sel = selectedPaperId === p.paper_id;
              return (
                <li
                  key={p.paper_id}
                  data-paper-id={p.paper_id}
                  data-sf-selected={sel ? 'true' : undefined}
                  onClick={() => actions.selectPaper(p.paper_id, false)}
                  style={{
                    padding: '10px 12px',
                    cursor: 'pointer',
                    borderBottom: '1px solid var(--sf-border)',
                  }}
                >
                  <div className="font-body" style={{ fontSize: 14, marginBottom: 4 }}>
                    <span
                      className="font-mono"
                      style={{ fontSize: 11, color: 'var(--sf-muted)', marginRight: 8 }}
                    >
                      [{i + 1}]
                    </span>
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
                    <span>{p.citation_count || 0} {t('common.cite')}</span>
                    <span>★{(p.final_score ?? 0).toFixed(1)}</span>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </main>
  );
}