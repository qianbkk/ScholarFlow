// Search context — owns the current search state, query, result, progress, errors.
// v2 has a flatter shape than v1: one context, one reducer, no prop drilling.

import {
  createContext,
  useContext,
  useReducer,
  useEffect,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react';
import type { NodeProgress, SearchResult, StreamEvent } from '../types/domain';
import { startSearch, cancelSearch } from '../services/api';

interface SearchState {
  query: string;
  loading: boolean;
  error: string | null;
  result: SearchResult | null;
  progress: NodeProgress[];
  costUsd: number;
  tokensUsed: number;
  startedAt: number | null;
  searchId: string | null;
  events: StreamEvent[];
}

type Action =
  | { type: 'set_query'; query: string }
  | { type: 'start'; query: string; searchId: string; startedAt: number }
  | { type: 'event'; event: StreamEvent }
  | { type: 'progress'; progress: NodeProgress }
  | { type: 'cost'; costUsd: number; tokensUsed: number }
  | { type: 'done'; result: SearchResult }
  | { type: 'error'; error: string }
  | { type: 'reset' }
  | { type: 'cancel' };

const initial: SearchState = {
  query: '',
  loading: false,
  error: null,
  result: null,
  progress: [],
  costUsd: 0,
  tokensUsed: 0,
  startedAt: null,
  searchId: null,
  events: [],
};

function reducer(state: SearchState, action: Action): SearchState {
  switch (action.type) {
    case 'set_query':
      return { ...state, query: action.query };
    case 'start':
      return {
        ...state,
        query: action.query,
        loading: true,
        error: null,
        result: null,
        progress: [],
        costUsd: 0,
        tokensUsed: 0,
        startedAt: action.startedAt,
        searchId: action.searchId,
        events: [],
      };
    case 'event':
      return { ...state, events: [...state.events, action.event] };
    case 'progress': {
      const idx = state.progress.findIndex((p) => p.node_id === action.progress.node_id);
      const next = state.progress.slice();
      if (idx === -1) {
        next.push(action.progress);
      } else {
        next[idx] = action.progress;
      }
      return { ...state, progress: next };
    }
    case 'cost':
      return { ...state, costUsd: action.costUsd, tokensUsed: action.tokensUsed };
    case 'done':
      return { ...state, loading: false, result: action.result };
    case 'error':
      return { ...state, loading: false, error: action.error };
    case 'cancel':
      return { ...state, loading: false, error: 'cancelled' };
    case 'reset':
      return { ...initial, query: state.query };
    default:
      return state;
  }
}

interface SearchContextValue {
  state: SearchState;
  setQuery: (q: string) => void;
  submit: (q: string) => Promise<void>;
  cancel: () => Promise<void>;
  reset: () => void;
}

const SearchContext = createContext<SearchContextValue | null>(null);

const NODE_LABELS: Record<string, string> = {
  query_decomposer: 'Decompose',
  query_refiner: 'Refine',
  paper_searcher: 'Search',
  relevance_scorer: 'Score',
  evidence_extractor: 'Extract',
  gap_analyzer: 'Gap',
  critic: 'Critique',
  synthesis: 'Synthesize',
};

export function SearchProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);

  const setQuery = useCallback((query: string) => dispatch({ type: 'set_query', query }), []);

  const submit = useCallback(async (q: string) => {
    if (!q.trim()) return;
    const searchId = `sf_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    dispatch({ type: 'start', query: q, searchId, startedAt: Date.now() });

    const controller = new AbortController();
    const startTime = Date.now();

    try {
      await startSearch({
        query: q,
        onEvent: (e) => {
          dispatch({ type: 'event', event: e });
          // Progress updates
          if (e.event === 'node_start') {
            const nodeId = String(e.data.node_id ?? '');
            dispatch({
              type: 'progress',
              progress: {
                node_id: nodeId,
                label: NODE_LABELS[nodeId] ?? nodeId,
                status: 'running',
                started_at: Date.now(),
              },
            });
          } else if (e.event === 'node_end') {
            const nodeId = String(e.data.node_id ?? '');
            dispatch({
              type: 'progress',
              progress: {
                node_id: nodeId,
                label: NODE_LABELS[nodeId] ?? nodeId,
                status: e.data.error ? 'error' : 'done',
                started_at: undefined,
                finished_at: Date.now(),
                hint: typeof e.data.hint === 'string' ? e.data.hint : undefined,
              },
            });
          } else if (e.event === 'cost') {
            const cost = Number(e.data.cost_usd ?? 0);
            const tokens = Number(e.data.tokens ?? 0);
            dispatch({ type: 'cost', costUsd: cost, tokensUsed: tokens });
          } else if (e.event === 'graph_snapshot') {
            // Handled by GraphPanel via events list if needed.
          }
        },
        onError: (err) => dispatch({ type: 'error', error: err.message }),
        onDone: (result) => {
          dispatch({ type: 'done', result });
          const elapsed = (Date.now() - startTime) / 1000;
          // eslint-disable-next-line no-console
          console.info(`[scholarflow] search done in ${elapsed.toFixed(1)}s`);
        },
        signal: controller.signal,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      dispatch({ type: 'error', error: message });
    }
  }, []);

  const cancel = useCallback(async () => {
    if (state.searchId) {
      await cancelSearch(state.searchId).catch(() => {
        /* ignore */
      });
    }
    dispatch({ type: 'cancel' });
  }, [state.searchId]);

  const reset = useCallback(() => dispatch({ type: 'reset' }), []);

  // Reduced-motion: no entrance animation needed.
  useEffect(() => {
    document.documentElement.dataset.search = state.loading ? 'loading' : 'idle';
  }, [state.loading]);

  const value = useMemo(
    () => ({ state, setQuery, submit, cancel, reset }),
    [state, setQuery, submit, cancel, reset],
  );

  return <SearchContext.Provider value={value}>{children}</SearchContext.Provider>;
}

export function useSearch(): SearchContextValue {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error('useSearch must be used inside <SearchProvider>');
  return ctx;
}
