/**
 * R10.5.30 (D7 P2-3): PaperFilters 类型 + DEFAULT_FILTERS 共享.
 *
 * 抽 lib/paperFilters.ts, 消除 App.tsx / FilterPanel.tsx / 未来
 * ReportPanel.tsx 各自 inline 重复定义 PaperFilters. R10.5.29 code-review
 * #1 已经标 deferred, 这一版正式落.
 */
export interface PaperFilters {
  yearRange: 'all' | '1' | '3' | '5';
  methods: string[];
  minConfidence: number;
  minQualityScore: number;
}

export const DEFAULT_FILTERS: PaperFilters = {
  yearRange: 'all',
  methods: [],
  minConfidence: 0,
  minQualityScore: 0,
};
