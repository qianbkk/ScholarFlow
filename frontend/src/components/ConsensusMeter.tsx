/**
 * ConsensusMeter — R10.5.93 (升级 1/2) 借鉴 Consensus.app 立场聚合可视化
 *
 * 显示 stance_classifier 节点输出的聚合: 支持/反对/中性/混合 的占比条 +
 * 1 句文字总结 + 多数立场.
 *
 * 设计目标:
 * - 一眼看出"主流学界怎么看" (Consensus 招牌功能)
 * - 跟 PaperList 的 stance 徽标呼应, 视觉语言一致
 * - 空状态友好: 没跑 stance_classifier / 失败时显示 placeholder
 */
import { useMemo } from 'react';
import type { StanceSummary } from '../types';

interface Props {
  summary: StanceSummary | null | undefined;
}

// 立场颜色 (跟 PaperList.STANCE_STYLE 对齐)
const STANCE_COLORS = {
  supporting: '#15803d',
  contrasting: '#b91c1c',
  mixed: '#b45309',
  neutral: '#78716c',
  unsure: '#a8a29e',
} as const;

const STANCE_LABELS = {
  supporting: '支持',
  contrasting: '反对',
  mixed: '混合',
  neutral: '中性',
  unsure: '未分类',
} as const;

export function ConsensusMeter({ summary }: Props) {
  // 空状态: 没数据
  const isEmpty = !summary || summary.total === 0;
  const counts = useMemo(() => {
    if (isEmpty) return null;
    return summary.counts;
  }, [summary, isEmpty]);

  if (isEmpty) return null;

  // 计算每个立场的百分比 (排除 unsure)
  const total = summary.total;
  const nonUnsure = total - (counts?.unsure || 0);
  const pct = (n: number) => (nonUnsure > 0 ? Math.round((n / nonUnsure) * 100) : 0);

  // 多数立场
  const majority = summary.majority_stance || 'unsure';
  const majorityLabel = STANCE_LABELS[majority as keyof typeof STANCE_LABELS] || '未知';

  // Top 3 study_types
  const topTypes = useMemo(() => {
    const entries = Object.entries(summary.type_counts || {})
      .filter(([k, v]) => v > 0 && k !== 'other')
      .sort(([, a], [, b]) => b - a)
      .slice(0, 3);
    return entries;
  }, [summary]);

  return (
    <section
      style={{
        margin: '20px 0 16px',
        padding: '16px 20px',
        border: '1px solid var(--sf-border)',
        backgroundColor: 'var(--sf-surface)',
        borderRadius: 2,
      }}
      data-testid="consensus-meter"
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <h3
          className="font-ui"
          style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: 'var(--sf-muted)',
            margin: 0,
          }}
        >
          · 立场聚合 · CONSENSUS
        </h3>
        <span
          className="font-mono"
          style={{ fontSize: 10, color: 'var(--sf-muted)' }}
        >
          n = {total} 篇
        </span>
      </div>

      {/* 立场百分比条: 4 段拼接, 宽度按 nonUnsure 比例 */}
      {nonUnsure > 0 && (
        <div
          style={{
            display: 'flex',
            height: 6,
            borderRadius: 3,
            overflow: 'hidden',
            backgroundColor: 'var(--sf-border)',
            marginBottom: 10,
          }}
          aria-label="立场分布"
        >
          {(['supporting', 'contrasting', 'mixed', 'neutral'] as const).map((key) => {
            const value = counts?.[key] || 0;
            if (value === 0) return null;
            const w = (value / nonUnsure) * 100;
            return (
              <div
                key={key}
                style={{
                  width: `${w}%`,
                  backgroundColor: STANCE_COLORS[key],
                  transition: 'width 300ms ease',
                }}
                title={`${STANCE_LABELS[key]}: ${value} (${pct(value)}%)`}
                data-testid={`consensus-segment-${key}`}
              />
            );
          })}
        </div>
      )}

      {/* 4 个立场数字 + label */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 12,
          marginBottom: 12,
        }}
      >
        {(['supporting', 'contrasting', 'mixed', 'neutral'] as const).map((key) => {
          const value = counts?.[key] || 0;
          if (value === 0 && key !== 'supporting' && key !== 'contrasting') return null;
          return (
            <div
              key={key}
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 4,
                minWidth: 56,
              }}
            >
              <span
                className="font-mono"
                style={{
                  fontSize: 16,
                  fontWeight: 600,
                  color: STANCE_COLORS[key],
                }}
                data-testid={`consensus-count-${key}`}
              >
                {value}
              </span>
              <span
                className="font-ui"
                style={{
                  fontSize: 10,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  color: 'var(--sf-muted)',
                }}
              >
                {STANCE_LABELS[key]}
              </span>
            </div>
          );
        })}
      </div>

      {/* 文字总结 */}
      <p
        className="font-body"
        style={{
          fontSize: 13,
          lineHeight: 1.5,
          color: 'var(--sf-text)',
          margin: '0 0 10px',
        }}
        data-testid="consensus-summary"
      >
        {summary.summary}
        {majority !== 'unsure' && (
          <>
            {' · 主流立场: '}
            <strong style={{ color: STANCE_COLORS[majority as keyof typeof STANCE_COLORS] }}>
              {majorityLabel}
            </strong>
          </>
        )}
      </p>

      {/* Top 3 study_types */}
      {topTypes.length > 0 && (
        <div
          className="font-mono"
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            fontSize: 10,
            color: 'var(--sf-muted)',
          }}
        >
          <span style={{ letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            主流类型:
          </span>
          {topTypes.map(([type, n]) => (
            <span
              key={type}
              style={{
                padding: '1px 6px',
                border: '1px solid var(--sf-border)',
                backgroundColor: 'var(--sf-bg)',
                borderRadius: 2,
              }}
            >
              {type} ×{n}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
