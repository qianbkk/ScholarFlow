// v4 state — single module-scope reactive store.
// v3 had 13 useState + 3 contexts. v4 has one store + a useStore hook.

import type { NodeProgress, Paper, SearchResult } from '../types';

export type AppMode = 'empty' | 'running' | 'done';
export type Overlay = null | 'graph' | 'papers' | 'compare';

export interface StoreState {
  mode: AppMode;
  query: string;
  result: SearchResult | null;
  cost: number;
  tokens: number;
  startedAt: number | null;
  nodes: NodeProgress[];
  selected: string[];
  hovered: string | null;
  // The currently-expanded inline paper card in the report
  expandedPaperId: string | null;
  // ⌘G / ⌘P / ⌘E overlays
  overlay: Overlay;
  searchId: string | null;
  error: string | null;
}

const PIPELINE: Array<{ id: string; label: string }> = [
  { id: 'query_decomposer', label: 'Decompose' },
  { id: 'query_refiner', label: 'Refine' },
  { id: 'paper_searcher', label: 'Search' },
  { id: 'relevance_scorer', label: 'Score' },
  { id: 'evidence_extractor', label: 'Extract' },
  { id: 'gap_analyzer', label: 'Gap' },
  { id: 'critic', label: 'Critique' },
  { id: 'synthesis', label: 'Synthesize' },
];

function initialNodes(): NodeProgress[] {
  return PIPELINE.map((n) => ({
    node_id: n.id,
    label: n.label,
    status: 'pending' as const,
    started_at: null,
    finished_at: null,
  }));
}

function initial(): StoreState {
  return {
    mode: 'empty',
    query: '',
    result: null,
    cost: 0,
    tokens: 0,
    startedAt: null,
    nodes: initialNodes(),
    selected: [],
    hovered: null,
    expandedPaperId: null,
    overlay: null,
    searchId: null,
    error: null,
  };
}

let state: StoreState = initial();
const listeners = new Set<() => void>();

function notify() {
  for (const l of listeners) l();
}

export const store = {
  get(): StoreState {
    return state;
  },
  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
  setQuery(q: string) {
    state = { ...state, query: q };
    notify();
  },
  startSearch() {
    state = {
      ...initial(),
      mode: 'running',
      query: state.query,
      startedAt: Date.now(),
      nodes: initialNodes(),
    };
    notify();
  },
  finishSearch(result: SearchResult) {
    state = { ...state, mode: 'done', result, searchId: result.search_id };
    notify();
  },
  failSearch(err: string) {
    state = { ...state, mode: 'empty', error: err };
    notify();
  },
  updateNode(nodeId: string, patch: Partial<NodeProgress>) {
    state = {
      ...state,
      nodes: state.nodes.map((n) => (n.node_id === nodeId ? { ...n, ...patch } : n)),
    };
    notify();
  },
  setCost(cost: number, tokens: number) {
    state = { ...state, cost, tokens };
    notify();
  },
  expandPaper(id: string | null) {
    state = { ...state, expandedPaperId: id };
    notify();
  },
  toggleSelect(id: string) {
    if (state.selected.includes(id)) {
      state = { ...state, selected: state.selected.filter((x) => x !== id) };
    } else {
      const next = [...state.selected, id];
      if (next.length > 2) next.shift();
      state = { ...state, selected: next };
    }
    notify();
  },
  clearSelect() {
    state = { ...state, selected: [] };
    notify();
  },
  setHover(id: string | null) {
    state = { ...state, hovered: id };
    notify();
  },
  setOverlay(o: Overlay) {
    state = { ...state, overlay: o };
    notify();
  },
  reset() {
    state = initial();
    notify();
  },
};

export { PIPELINE };
export type { Paper };
