/**
 * SearchSummary — R10.5.59 Search 视图概要卡
 *
 * 在 Search tab 显示的"摘要结果". 不渲染完整报告 (报告在 Report tab),
 * 只显示: 报告标题 (从 Markdown 一级标题抽) + Top 5 论文 + 跳到报告按钮.
 *
 * 用户跑完查询后看到概要, 决定是否要看完整报告.
 */
import { useMemo } from 'react';
import { useStore, actions } from '../store/useStore';
import { useT } from '../i18n';
import type { Paper } from '../types';

function extractTitle(md: string): string {
  // 第一行 ## 标题优先, 否则 # 标题, 否则 fallback
  const lines = md.split('\n').map((l) => l.trim()).filter(Boolean);
  for (const l of lines) {
    const h2 = l.match(/^#{1,2}\s+(.+)$/);
    if (h2) return h2[1].trim();
  }
  return '';
}

export function SearchSummary() {
  const result = useStore((s) => s.result);
  const loading = useStore((s) => s.loading);
  const t = useT();

  const title = useMemo(() => extractTitle(result?.report ?? ''), [result]);
  const papers: Paper[] = result?.ranked_papers ?? [];
  const top5 = papers.slice(0, 5);

  if (!result || loading) return null;

  const totalCost = result.total_cost_usd?.toFixed(4) ?? '0.0000';
  const totalTokens = result.total_tokens_used ?? 0;
  const elapsed = result.elapsed_seconds?.toFixed(1) ?? '—';
  const iters = result.iteration ?? 0;

  return (
    <section
      style={{
        marginTop: 32,
        padding: '20px 0',
        borderTop: '1px solid var(--sf-border)',
      }}
      data-testid="search-summary"
    >
      {/* Meta row */}
      <div
        className="font-mono"
        style={{
          fontSize: 10,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--sf-muted)',
          marginBottom: 8,
        }}
      >
        {t('summary.meta', { n: papers.length, iters, cost: totalCost, tokens: totalTokens, sec: elapsed })}
      </div>

      {/* Title */}
      {title && (
        <h2
          className="font-display"
          style={{
            fontSize: 24,
            lineHeight: 1.25,
            letterSpacing: '-0.02em',
            margin: '0 0 16px',
            color: 'var(--sf-text)',
          }}
        >
          {title}
        </h2>
      )}

      {/* Top 5 */}
      {top5.length > 0 && (
        <ol
          style={{
            listStyle: 'none',
            counterReset: 'sf-summary',
            padding: 0,
            margin: '0 0 16px',
          }}
        >
          {top5.map((p, i) => (
            <li
              key={p.paper_id || `${i}-${p.title}`}
              style={{
                counterIncrement: 'sf-summary',
                position: 'relative',
                padding: '8px 0 8px 28px',
                borderTop: i > 0 ? '1px solid var(--sf-border)' : 'none',
              }}
            >
              <span
                className="font-mono"
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 8,
                  fontSize: 10,
                  color: 'var(--sf-accent)',
                  fontWeight: 600,
                }}
              >
                {String(i + 1).padStart(2, '0')}
              </span>
              <div
                className="font-body"
                style={{
                  fontSize: 14,
                  color: 'var(--sf-text)',
                  lineHeight: 1.4,
                }}
              >
                {p.title}
              </div>
              <div
                className="font-mono"
                style={{
                  fontSize: 10,
                  color: 'var(--sf-muted)',
                  marginTop: 2,
                }}
              >
                {p.authors?.slice(0, 3).join(', ')}
                {p.authors && p.authors.length > 3 ? ' et al.' : ''}
                {' · '}
                {p.year || '—'}
                {' · '}
                {t('summary.cites', { n: p.citation_count ?? 0 })}
                {p.final_score ? ` · ★${p.final_score.toFixed(1)}` : ''}
              </div>
            </li>
          ))}
        </ol>
      )}

      {/* View full report button */}
      <button
        type="button"
        onClick={() => actions.setView('report')}
        className="sf-btn sf-btn-primary font-ui"
        data-testid="view-full-report-btn"
        style={{ marginTop: 8 }}
      >
        {t('summary.viewReport')} →
      </button>
    </section>
  );
}