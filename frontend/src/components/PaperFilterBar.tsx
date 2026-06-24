/**
 * PaperFilterBar — R10.5.93 (升级 3) 借鉴 Consensus.app + Elicit 过滤栏
 *
 * 让用户能按:
 * - stance 立场 (支持/反对/中性/混合)
 * - study_type 研究类型 (RCT / Meta / Review / ...)
 * 过滤当前 ranked_papers 列表.
 *
 * 设计: 单选按钮组 + 计数 badge, 跟 PaperList 的徽标视觉语言一致.
 */
import { useMemo } from 'react';
import type { Paper } from '../types';

export interface PaperFilters {
  stance: string | null;       // null = 全部
  studyType: string | null;    // null = 全部
}

interface Props {
  papers: Paper[];
  filters: PaperFilters;
  onChange: (f: PaperFilters) => void;
}

// 立场选项 (跟 PaperList.STANCE_STYLE + ConsensusMeter 对齐)
// R10.5.98 (impeccable audit P2): 颜色用 --sf-stance-* CSS vars, 4 主题自动适配.
const STANCE_OPTIONS: Array<{ key: string; label: string; emoji: string; color: string }> = [
  { key: 'all',         label: '全部',   emoji: '·', color: 'var(--sf-muted)' },
  { key: 'supporting',  label: '支持',   emoji: '✓', color: 'var(--sf-stance-supporting)' },
  { key: 'contrasting', label: '反对',   emoji: '✗', color: 'var(--sf-stance-contrasting)' },
  { key: 'mixed',       label: '混合',   emoji: '≈', color: 'var(--sf-stance-mixed)' },
  { key: 'neutral',     label: '中性',   emoji: '·', color: 'var(--sf-stance-neutral)' },
];

// study_type 选项 (Elicit 风格)
const STUDY_TYPE_OPTIONS: Array<{ key: string; label: string }> = [
  { key: 'all',               label: '全部' },
  { key: 'rct',               label: 'RCT' },
  { key: 'meta-analysis',     label: 'Meta-analysis' },
  { key: 'systematic-review', label: 'Systematic Review' },
  { key: 'review',            label: 'Review' },
  { key: 'method',            label: 'Method' },
  { key: 'empirical',         label: 'Empirical' },
  { key: 'case-study',        label: 'Case Study' },
  { key: 'survey',            label: 'Survey' },
];

export function PaperFilterBar({ papers, filters, onChange }: Props) {
  // 计算每个 stance / study_type 的实际计数 (基于当前 papers)
  const stanceCounts = useMemo(() => {
    const counts: Record<string, number> = { all: papers.length };
    for (const p of papers) {
      const k = p.stance || 'unsure';
      counts[k] = (counts[k] || 0) + 1;
    }
    return counts;
  }, [papers]);

  const studyTypeCounts = useMemo(() => {
    const counts: Record<string, number> = { all: papers.length };
    for (const p of papers) {
      const k = p.study_type || 'other';
      counts[k] = (counts[k] || 0) + 1;
    }
    return counts;
  }, [papers]);

  // 只显示有论文的 study_type 按钮 (避免空 category 噪声)
  const visibleStudyTypes = useMemo(() => {
    return STUDY_TYPE_OPTIONS.filter((o) => o.key === 'all' || (studyTypeCounts[o.key] || 0) > 0);
  }, [studyTypeCounts]);

  // 是否有过滤生效
  const hasActiveFilter = filters.stance !== null || filters.studyType !== null;

  if (papers.length === 0) return null;

  return (
    <section
      style={{
        marginTop: 32,
        padding: '12px 0',
        borderTop: '1px solid var(--sf-border)',
        borderBottom: '1px solid var(--sf-border)',
      }}
      data-testid="paper-filter-bar"
    >
      {/* Stance 过滤行 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 8,
          marginBottom: 8,
        }}
      >
        <span
          className="font-mono"
          style={{
            fontSize: 10,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: 'var(--sf-muted)',
            marginRight: 4,
            minWidth: 60,
          }}
        >
          立场
        </span>
        {STANCE_OPTIONS.map((opt) => {
          const isActive = (filters.stance || 'all') === opt.key;
          const count = stanceCounts[opt.key] || 0;
          // 跳过 0 计数的非"all"按钮
          if (opt.key !== 'all' && count === 0) return null;
          return (
            <button
              key={opt.key}
              type="button"
              onClick={() => onChange({
                ...filters,
                stance: opt.key === 'all' ? null : opt.key,
              })}
              className="font-mono"
              style={{
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: '0.05em',
                padding: '4px 8px',
                color: isActive ? opt.color : 'var(--sf-muted)',
                backgroundColor: isActive ? 'var(--sf-surface-alt)' : 'transparent',
                border: `1px solid ${isActive ? opt.color : 'var(--sf-border)'}`,
                borderRadius: 2,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
              data-testid={`filter-stance-${opt.key}`}
              aria-pressed={isActive}
            >
              <span>{opt.emoji}</span>
              <span>{opt.label}</span>
              <span style={{ opacity: 0.6 }}>×{count}</span>
            </button>
          );
        })}
      </div>

      {/* Study type 过滤行 */}
      {visibleStudyTypes.length > 1 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 6,
          }}
        >
          <span
            className="font-mono"
            style={{
              fontSize: 10,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--sf-muted)',
              marginRight: 4,
              minWidth: 60,
            }}
          >
            类型
          </span>
          {visibleStudyTypes.map((opt) => {
            const isActive = (filters.studyType || 'all') === opt.key;
            const count = studyTypeCounts[opt.key] || 0;
            return (
              <button
                key={opt.key}
                type="button"
                onClick={() => onChange({
                  ...filters,
                  studyType: opt.key === 'all' ? null : opt.key,
                })}
                className="font-mono"
                style={{
                  fontSize: 10,
                  fontWeight: 500,
                  padding: '3px 7px',
                  color: isActive ? 'var(--sf-text)' : 'var(--sf-muted)',
                  backgroundColor: isActive ? 'var(--sf-surface-alt)' : 'transparent',
                  border: `1px solid ${isActive ? 'var(--sf-accent)' : 'var(--sf-border)'}`,
                  borderRadius: 2,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                }}
                data-testid={`filter-studytype-${opt.key}`}
                aria-pressed={isActive}
              >
                <span>{opt.label}</span>
                <span style={{ opacity: 0.6 }}>×{count}</span>
              </button>
            );
          })}
          {hasActiveFilter && (
            <button
              type="button"
              onClick={() => onChange({ stance: null, studyType: null })}
              className="font-mono"
              style={{
                fontSize: 10,
                fontWeight: 500,
                padding: '3px 7px',
                color: 'var(--sf-accent)',
                backgroundColor: 'transparent',
                border: 'none',
                cursor: 'pointer',
                textDecoration: 'underline',
                textUnderlineOffset: 2,
              }}
              data-testid="filter-clear"
            >
              清空
            </button>
          )}
        </div>
      )}
    </section>
  );
}
