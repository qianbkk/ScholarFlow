/**
 * R10.5.31 (F4): SelectionContext
 *
 * 装: 论文/图谱选中相关 state — 跨 QueryPanel/ReportPanel/GraphPanel
 *     三面板共享, 之前是 6 条 props drilling. 现在 1 个 context.
 *
 * State 拆分:
 *   focusedPaperId     — 单篇聚焦 (3 面板同步高亮)
 *   selectedPaperIds   — 多选 (凑 2 篇触发 CompareDrawer)
 *   expandedNodeId     — 图谱节点展开 (CockpitDashboard 用)
 *   filters            — 全局过滤器
 *
 * 用 useReducer 替代 4 个 useState, 后续加新 action 直接扩 union.
 */
import { createContext, useContext, useMemo, useReducer, type ReactNode } from 'react';
import { DEFAULT_FILTERS, type PaperFilters } from '../lib/paperFilters';

interface SelectionState {
  focusedPaperId: string | null;
  selectedPaperIds: string[];
  expandedNodeId: string | null;
  filters: PaperFilters;
}

type Action =
  | { type: 'focusPaper'; paperId: string | null }
  | { type: 'togglePaperSelection'; paperId: string }
  | { type: 'clearPaperSelection' }
  | { type: 'expandNode'; nodeId: string | null }
  | { type: 'setFilters'; filters: PaperFilters }
  | { type: 'patchFilters'; patch: Partial<PaperFilters> }
  | { type: 'resetFilters' };

function reducer(state: SelectionState, action: Action): SelectionState {
  switch (action.type) {
    case 'focusPaper':
      return { ...state, focusedPaperId: action.paperId };
    case 'togglePaperSelection': {
      // 最多保留 2 篇, 凑齐触发 CompareDrawer.
      const exists = state.selectedPaperIds.includes(action.paperId);
      if (exists) {
        return {
          ...state,
          selectedPaperIds: state.selectedPaperIds.filter((id) => id !== action.paperId),
        };
      }
      const next = [...state.selectedPaperIds, action.paperId].slice(-2);
      return { ...state, selectedPaperIds: next };
    }
    case 'clearPaperSelection':
      return { ...state, selectedPaperIds: [] };
    case 'expandNode':
      return { ...state, expandedNodeId: action.nodeId };
    case 'setFilters':
      return { ...state, filters: action.filters };
    case 'patchFilters':
      return { ...state, filters: { ...state.filters, ...action.patch } };
    case 'resetFilters':
      return { ...state, filters: DEFAULT_FILTERS };
    default:
      return state;
  }
}

interface SelectionContextValue {
  state: SelectionState;
  focusPaper: (paperId: string | null) => void;
  togglePaperSelection: (paperId: string) => void;
  clearPaperSelection: () => void;
  expandNode: (nodeId: string | null) => void;
  setFilters: (filters: PaperFilters) => void;
  patchFilters: (patch: Partial<PaperFilters>) => void;
  resetFilters: () => void;
}

const SelectionContext = createContext<SelectionContextValue | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, {
    focusedPaperId: null,
    selectedPaperIds: [],
    expandedNodeId: null,
    filters: DEFAULT_FILTERS,
  });

  // 用 useMemo 包 dispatch, 避免子组件 re-render 风暴.
  const value = useMemo<SelectionContextValue>(
    () => ({
      state,
      focusPaper: (paperId) => dispatch({ type: 'focusPaper', paperId }),
      togglePaperSelection: (paperId) => dispatch({ type: 'togglePaperSelection', paperId }),
      clearPaperSelection: () => dispatch({ type: 'clearPaperSelection' }),
      expandNode: (nodeId) => dispatch({ type: 'expandNode', nodeId }),
      setFilters: (filters) => dispatch({ type: 'setFilters', filters }),
      patchFilters: (patch) => dispatch({ type: 'patchFilters', patch }),
      resetFilters: () => dispatch({ type: 'resetFilters' }),
    }),
    [state]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionContextValue {
  const ctx = useContext(SelectionContext);
  if (!ctx) {
    throw new Error('useSelection must be used within <SelectionProvider>');
  }
  return ctx;
}
