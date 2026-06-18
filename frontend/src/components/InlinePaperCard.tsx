/**
 * InlinePaperCard — 报告内嵌论文卡片 (R10.5.40 Agent 1, Phase 2)
 *
 * 从 v4 prototype (newversion/frontend/src/ui/PaperFootnote.tsx) 吸收的设计:
 *   - 论文卡片在用户点击引用时, 直接出现在引用下方 (inline)
 *   - 不是侧栏, 不是 modal — 保持阅读流
 *   - 一次只显示一个, 点击外部 / × 关闭
 *   - 包含 title / authors / year / venue / 摘要 (截断到 240 字) / "open" / "+ compare"
 *
 * 不要做的:
 *   - 不实现 compare drawer 交互 (Agent 4 拥有 CompareDrawer 表面)
 *   - "+ compare" 按钮只调 onCompare 回调, 父组件决定行为
 *
 * 样式策略:
 *   - 复用现有 --sf-* CSS 变量, 跟 ReportPanel 报告正文风格一致
 *   - 学术期刊脚注卡片观感 (border-left + bg-elev + 印刷感字体)
 */
import { useEffect, useRef } from 'react';
import type { Paper } from '../types';

const ABSTRACT_PREVIEW_LIMIT = 240;

function truncate(s: string, n: number): string {
  if (!s) return '';
  if (s.length <= n) return s;
  return s.slice(0, n).trimEnd() + '…';
}

interface Props {
  paper: Paper;
  /** 1-based index for display ([01], [02], ...) — 跟 ReportPanel 来源一览对齐 */
  index: number;
  /** 关闭回调 — ReportPanel 在引用区下方卸载这个卡片 */
  onClose: () => void;
  /** "+ compare" 按钮回调 — Agent 4 拥有 CompareDrawer, 此处只 emit 选中事件.
   *  不强制要求, 父组件可省略. */
  onCompare?: () => void;
}

export function InlinePaperCard({ paper, index, onClose, onCompare }: Props) {
  // R10.5.40 (Agent 1): Esc 关闭 — 跟 v4 ReportView 行为一致.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const cardRef = useRef<HTMLElement | null>(null);

  const authors = Array.isArray(paper.authors) ? paper.authors : [];
  const authorsDisplay =
    authors.slice(0, 5).join(', ') + (authors.length > 5 ? ` +${authors.length - 5}` : '');
  const abstractPreview = truncate(paper.abstract || '', ABSTRACT_PREVIEW_LIMIT);

  return (
    <aside
      ref={cardRef}
      className="sf-inline-paper-card my-5 px-4 py-3 font-ui"
      role="complementary"
      aria-label={`论文详情 ${index}`}
      data-testid="inline-paper-card"
      data-paper-id={paper.paper_id}
    >
      {/* 顶部: 编号 + 标题 + 关闭 × */}
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-baseline gap-2 min-w-0 flex-1">
          <span
            className="font-mono text-[10px] tabular-nums shrink-0"
            style={{ color: 'var(--sf-muted)' }}
          >
            [{String(index).padStart(2, '0')}]
          </span>
          <h4
            className="font-display italic font-semibold text-[14px] leading-snug min-w-0 flex-1"
            style={{ color: 'var(--sf-text)' }}
          >
            {paper.title}
          </h4>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭论文详情"
          title="关闭 (Esc)"
          className="font-display italic text-lg leading-none shrink-0 px-1 transition"
          style={{ color: 'var(--sf-muted)' }}
          data-testid="inline-paper-card-close"
        >
          ×
        </button>
      </div>

      {/* 元数据: 作者 · 年份 · venue */}
      <div
        className="font-mono text-[10px] uppercase tracking-wider mb-2"
        style={{ color: 'var(--sf-muted)' }}
      >
        {authorsDisplay || '—'}
        {paper.year ? ` · ${paper.year}` : ''}
        {paper.venue ? ` · ${paper.venue}` : ''}
      </div>

      {/* 摘要预览 (240 字截断 + 4 行 line-clamp) */}
      {abstractPreview && (
        <p
          className="sf-abstract-preview font-body text-[12.5px] leading-relaxed mb-3"
          style={{ color: 'var(--sf-text)' }}
        >
          {abstractPreview}
        </p>
      )}

      {/* 指标行: 引用数 + 评分 */}
      <div
        className="flex items-center gap-4 font-mono text-[10px] tabular-nums mb-3 pb-3"
        style={{
          color: 'var(--sf-muted)',
          borderBottom: '1px solid var(--sf-border)',
        }}
      >
        <span>
          <span style={{ color: 'var(--sf-text)' }}>
            {(paper.citation_count ?? 0).toLocaleString()}
          </span>{' '}
          citations
        </span>
        <span>
          score{' '}
          <span style={{ color: 'var(--sf-accent)' }}>
            {paper.final_score?.toFixed(2) ?? '—'}
          </span>
        </span>
        {paper.doi && (
          <span className="truncate" title={paper.doi}>
            doi: <span style={{ color: 'var(--sf-text)' }}>{paper.doi}</span>
          </span>
        )}
      </div>

      {/* 操作行: open 链接 + compare 按钮 */}
      <div className="flex items-center gap-5">
        {paper.url && /^https?:\/\//i.test(paper.url) && (
          <a
            href={paper.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-[11px] uppercase tracking-[0.12em] transition"
            style={{ color: 'var(--sf-accent)' }}
            data-testid="inline-paper-card-open"
          >
            open ↗
          </a>
        )}
        {onCompare && (
          <button
            type="button"
            onClick={onCompare}
            className="font-mono text-[11px] uppercase tracking-[0.12em] transition"
            style={{
              color: 'var(--sf-accent)',
              background: 'transparent',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
            }}
            data-testid="inline-paper-card-compare"
          >
            + compare
          </button>
        )}
      </div>
    </aside>
  );
}