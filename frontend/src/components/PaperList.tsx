/**
 * PaperList — R10.5.54 论文编号列表
 *
 * 取代 QueryPanel 内的 paper list: 编号列表, 无 card, 2px 左侧 rule 仅选中态.
 * shift-click 第二篇 → CompareDrawer 打开.
 *
 * R10.5.93 (升级 1/3/4): 借鉴 Scite/Consensus/Elicit 三大工具:
 * - 每行展示 stance 徽标 (支持/反对/中性/混合)
 * - 每行展示 study_type 徽标 (RCT/meta-analysis/...)
 * - 每行展开 1 句 key_quote 关键引用 (Elicit 风格)
 */
import { useStore, actions } from '../store/useStore';
import type { Paper } from '../types';

// R10.5.93: stance 视觉映射. 颜色用 CSS var 跟 design system 对齐.
const STANCE_STYLE: Record<string, { label: string; emoji: string; color: string; bg: string }> = {
  supporting:  { label: '支持',     emoji: '✓', color: 'var(--sf-success, #15803d)', bg: 'rgba(21, 161, 67, 0.1)' },
  contrasting: { label: '反对',     emoji: '✗', color: 'var(--sf-danger,  #b91c1c)', bg: 'rgba(185, 28, 28, 0.1)' },
  mixed:       { label: '混合',     emoji: '≈', color: 'var(--sf-warning, #b45309)', bg: 'rgba(180, 83, 9, 0.1)' },
  neutral:     { label: '中性',     emoji: '·', color: 'var(--sf-muted,   #78716c)', bg: 'rgba(120, 113, 108, 0.1)' },
  unsure:      { label: '未分类',   emoji: '?', color: 'var(--sf-muted,   #a8a29e)', bg: 'transparent' },
};

// R10.5.93: study_type 标签映射 (Elicit 风格).
const STUDY_TYPE_LABEL: Record<string, string> = {
  'rct': 'RCT',
  'meta-analysis': 'Meta',
  'systematic-review': 'SysRev',
  'review': 'Review',
  'survey': 'Survey',
  'method': 'Method',
  'case-study': 'Case',
  'empirical': 'Empirical',
  'other': '—',
};

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
          // R10.5.93: stance + study_type + key_quote
          const stanceKey = p.stance || 'unsure';
          const stanceMeta = STANCE_STYLE[stanceKey] || STANCE_STYLE.unsure;
          const studyTypeLabel = p.study_type ? STUDY_TYPE_LABEL[p.study_type] || p.study_type : null;
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
                      alignItems: 'center',
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
                    {/* R10.5.93: stance 徽标 (Scite 风格) */}
                    {p.stance && p.stance !== 'unsure' && (
                      <span
                        className="font-mono"
                        style={{
                          fontSize: 9,
                          fontWeight: 600,
                          letterSpacing: '0.05em',
                          textTransform: 'uppercase',
                          padding: '1px 6px',
                          color: stanceMeta.color,
                          backgroundColor: stanceMeta.bg,
                          border: `1px solid ${stanceMeta.color}`,
                          borderRadius: '2px',
                        }}
                        title={`立场: ${stanceMeta.label}`}
                        data-testid="paper-stance"
                      >
                        {stanceMeta.emoji} {stanceMeta.label}
                      </span>
                    )}
                    {/* R10.5.93: study_type 徽标 (Elicit 风格) */}
                    {studyTypeLabel && studyTypeLabel !== '—' && (
                      <span
                        className="font-mono"
                        style={{
                          fontSize: 9,
                          fontWeight: 600,
                          letterSpacing: '0.05em',
                          textTransform: 'uppercase',
                          padding: '1px 6px',
                          color: 'var(--sf-muted)',
                          backgroundColor: 'var(--sf-surface)',
                          border: '1px solid var(--sf-border)',
                          borderRadius: '2px',
                        }}
                        title={`研究类型: ${p.study_type}`}
                        data-testid="paper-study-type"
                      >
                        {studyTypeLabel}
                      </span>
                    )}
                  </div>
                  {/* R10.5.93: key_quote 关键引用 (Elicit 风格) */}
                  {p.key_quote && (
                    <blockquote
                      className="font-body"
                      style={{
                        fontSize: 12,
                        lineHeight: 1.5,
                        color: 'var(--sf-muted)',
                        margin: '6px 0 0',
                        padding: '4px 0 4px 10px',
                        borderLeft: '2px solid var(--sf-border)',
                        fontStyle: 'italic',
                      }}
                      data-testid="paper-key-quote"
                    >
                      "{p.key_quote}"
                    </blockquote>
                  )}
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