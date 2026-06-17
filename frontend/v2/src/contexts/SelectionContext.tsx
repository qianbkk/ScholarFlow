// Selection context — owns the currently selected paper(s).
// Up to 2 papers can be selected for compare.

import { createContext, useContext, useReducer, useCallback, useMemo, type ReactNode } from 'react';

interface State {
  selectedIds: string[];
  hoveredId: string | null;
}

type Action =
  | { type: 'toggle'; id: string }
  | { type: 'select'; id: string }
  | { type: 'deselect'; id: string }
  | { type: 'hover'; id: string | null }
  | { type: 'clear' };

const initial: State = { selectedIds: [], hoveredId: null };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'toggle': {
      if (state.selectedIds.includes(action.id)) {
        return { ...state, selectedIds: state.selectedIds.filter((x) => x !== action.id) };
      }
      // Cap at 2 — kick the oldest.
      const next = [...state.selectedIds, action.id];
      if (next.length > 2) next.shift();
      return { ...state, selectedIds: next };
    }
    case 'select': {
      if (state.selectedIds.includes(action.id)) return state;
      const next = [...state.selectedIds, action.id];
      if (next.length > 2) next.shift();
      return { ...state, selectedIds: next };
    }
    case 'deselect':
      return { ...state, selectedIds: state.selectedIds.filter((x) => x !== action.id) };
    case 'hover':
      return { ...state, hoveredId: action.id };
    case 'clear':
      return { ...initial };
    default:
      return state;
  }
}

interface SelectionContextValue {
  state: State;
  toggle: (id: string) => void;
  select: (id: string) => void;
  deselect: (id: string) => void;
  hover: (id: string | null) => void;
  clear: () => void;
  isSelected: (id: string) => boolean;
}

const SelectionContext = createContext<SelectionContextValue | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);

  const toggle = useCallback((id: string) => dispatch({ type: 'toggle', id }), []);
  const select = useCallback((id: string) => dispatch({ type: 'select', id }), []);
  const deselect = useCallback((id: string) => dispatch({ type: 'deselect', id }), []);
  const hover = useCallback((id: string | null) => dispatch({ type: 'hover', id }), []);
  const clear = useCallback(() => dispatch({ type: 'clear' }), []);
  const isSelected = useCallback((id: string) => state.selectedIds.includes(id), [state.selectedIds]);

  const value = useMemo(
    () => ({ state, toggle, select, deselect, hover, clear, isSelected }),
    [state, toggle, select, deselect, hover, clear, isSelected],
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionContextValue {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error('useSelection must be used inside <SelectionProvider>');
  return ctx;
}
