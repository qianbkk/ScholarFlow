// v3 state — a single module-scope reactive store. The product is small
// enough that we don't need Redux/Zustand. The store exposes typed
// actions and a `subscribe` for fine-grained re-render.

import type { NodeProgress, Paper, SearchResult } from '../types';

export interface StoreState {
  query: string;
  running: boolean;
  error: string | null;
  result: SearchResult | null;
  cost: number;
  tokens: number;
  startedAt: number | null;
  nodes: NodeProgress[];
  selected: string[];
  hovered: string | null;
  events: Array<{ event: string; ts: number; data: unknown }>;
  searchId: string | null;
}

const PIPELINE = [
  { id: 'query_decomposer', label: 'Decompose' },
  { id: 'query_refiner', label: 'Refine' },
  { id: 'paper_searcher', label: 'Search' },
  { id: 'relevance_scorer', label: 'Score' },
  { id: 'evidence_extractor', label: 'Extract' },
  { id: 'gap_analyzer', label: 'Gap' },
  { id: 'critic', label: 'Critique' },
  { id: 'synthesis', label: 'Synthesize' },
];

function initial(): StoreState {
  return {
    query: '',
    running: false,
    error: null,
    result: null,
    cost: 0,
    tokens: 0,
    startedAt: null,
    nodes: PIPELINE.map((n) => ({ node_id: n.id, label: n.label, status: 'pending', started_at: null, finished_at: null })),
    selected: [],
    hovered: null,
    events: [],
    searchId: null,
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
    return () => listeners.delete(fn);
  },
  setQuery(q: string) {
    state = { ...state, query: q };
    notify();
  },
  startSearch() {
    state = {
      ...initial(),
      query: state.query,
      running: true,
      startedAt: Date.now(),
      nodes: PIPELINE.map((n) => ({ node_id: n.id, label: n.label, status: 'pending', started_at: null, finished_at: null })),
    };
    notify();
  },
  finishSearch(result: SearchResult) {
    state = { ...state, running: false, result, searchId: result.search_id };
    notify();
  },
  failSearch(err: string) {
    state = { ...state, running: false, error: err };
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
  pushEvent(event: string, data: unknown) {
    state = {
      ...state,
      events: [...state.events, { event, ts: Date.now(), data }].slice(-100),
    };
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
  setSearchId(id: string) {
    state = { ...state, searchId: id };
    notify();
  },
  reset() {
    state = initial();
    notify();
  },
};

export const PIPELINE_NODES = PIPELINE;
export type { Paper };
