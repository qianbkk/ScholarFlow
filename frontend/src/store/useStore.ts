/**
 * useStore — R10.5.54 单一 store
 *
 * 取代之前的 3 个 Context (AppContext + SelectionContext + UIContext) +
 * App.tsx 里散落的 13 个 useState. 这里是所有应用状态的唯一真相源.
 *
 * 设计原则:
 * - 平铺结构, 不用嵌套 slice (Zustand-style)
 * - 写操作是 set(action) 风格, 不是直接 setState
 * - 持久化 (theme/dark/recent/runtimeMode) 在初始化时同步加载,
 *   写入时立即同步到 localStorage
 */

import { useSyncExternalStore } from 'react';
import type { SearchResult, Paper } from '../types';
import type { ThemeId } from '../lib/tokens';
import type { Locale } from '../i18n';
import { applyTheme, THEMES } from '../lib/tokens';
import { STORAGE_KEYS } from '../lib/storageKeys';
import { getApiKey } from '../services/api';

// R10.5.59: 删 'settings' tab, 加 'about' tab. Settings 改左侧常驻菜单栏
export type ViewId = 'search' | 'report' | 'graph' | 'history' | 'about';
export type RuntimeMode = 'local' | 'llm';

// ===== Pipeline events =====
export interface NodeEvent {
  node: string;
  step: number;
  status: 'running' | 'completed' | 'error';
  model?: string;
  cost_usd?: number;
  tokens?: number;
  elapsed: number;
  iteration?: number;
}

export interface GraphSnapshot {
  iteration: number;
  graph: any;
  node_count: number;
  link_count: number;
}

export interface RecentEntry {
  query: string;
  source: 'real' | 'local' | 'unknown';
  ts: number;
}

export interface BudgetExceeded {
  cost_usd: number;
  budget_usd: number;
  message?: string;
  node?: string;
}

export interface User {
  user_id: string;
  display_name: string;
  email?: string;
  created_at?: string;
}

interface State {
  // View
  currentView: ViewId;

  // Theme (R10.5.55: 删除独立 isDark 状态, midnight 主题天然是暗色)
  theme: ThemeId;
  locale: Locale;

  // Auth
  user: User | null;
  hasApiKey: boolean;

  // Runtime
  runtimeMode: RuntimeMode;

  // Search
  query: string;
  loading: boolean;
  error: string | null;
  result: SearchResult | null;
  lastQuery: string;
  lastSubmittedQuery: string;
  elapsed: number;

  // Pipeline
  events: NodeEvent[];
  nodeThinking: Record<string, string[]>;
  graphSnapshots: GraphSnapshot[];
  expandedNodeId: string | null;
  budgetExceeded: BudgetExceeded | null;

  // Selection
  selectedPaperId: string | null;
  selectedPaperIds: string[];        // for compare drawer

  // History
  recentSearches: RecentEntry[];

  // UI flags
  commandPaletteOpen: boolean;
  compareDrawerOpen: boolean;
  authDialogOpen: boolean;
  changelogOpen: boolean;
  // R10.5.59: 左侧设置菜单常驻 + 可收起
  settingsCollapsed: boolean;
}

const initialState: State = {
  currentView: 'search',
  theme: 'parchment',
  locale: 'zh',
  user: null,
  hasApiKey: false,
  runtimeMode: 'llm',
  query: '',
  loading: false,
  error: null,
  result: null,
  lastQuery: '',
  lastSubmittedQuery: '',
  elapsed: 0,
  events: [],
  nodeThinking: {},
  graphSnapshots: [],
  expandedNodeId: null,
  budgetExceeded: null,
  selectedPaperId: null,
  selectedPaperIds: [],
  recentSearches: [],
  commandPaletteOpen: false,
  compareDrawerOpen: false,
  authDialogOpen: false,
  changelogOpen: false,
  settingsCollapsed: false,
};

// ===== Persistence helpers =====

function readStorage<T>(key: string, fallback: T, validate?: (v: unknown) => boolean): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    if (validate && !validate(parsed)) return fallback;
    return parsed as T;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: unknown): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota exceeded — silently drop, UI will fall back to defaults
  }
}

function readSession<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeSession(key: string, value: unknown): void {
  if (typeof window === 'undefined') return;
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}

// ===== Store implementation =====

let state: State = (() => {
  // Boot-time hydration from localStorage / sessionStorage
  const theme = readStorage<ThemeId>(
    STORAGE_KEYS.theme ?? 'sf-theme',
    'parchment',
    (v): v is ThemeId => typeof v === 'string' && v in THEMES
  );
  // R10.5.55: 旧 sf-dark-mode=true 自动迁移到 theme=midnight (兼容旧用户)
  const storedDark = readStorage<boolean>(
    STORAGE_KEYS.darkMode ?? 'sf-dark-mode',
    false
  );
  const locale = readStorage<Locale>(
    STORAGE_KEYS.locale ?? 'sf-locale',
    'zh',
    (v): v is Locale => v === 'zh' || v === 'en'
  );
  const effectiveTheme: ThemeId =
    storedDark && theme === 'parchment' ? 'midnight' : theme;
  const recent = readStorage<RecentEntry[]>(
    STORAGE_KEYS.recentSearches ?? 'sf-recent-searches',
    [],
    (v): boolean => Array.isArray(v) && v.every(
      (e) => e && typeof e === 'object' && typeof (e as RecentEntry).query === 'string'
    )
  );
  // R10.5.55: 接受旧值 'mock'/'real' 兼容, 规范化到新值. 用 union 字面量类型.
  type RuntimeModeStored = RuntimeMode | 'mock' | 'real';
  const runtimeModeStored = readStorage<RuntimeModeStored>(
    STORAGE_KEYS.runtimeMode ?? 'sf-runtime-mode',
    'llm',
    (v): v is RuntimeModeStored => v === 'local' || v === 'llm' || v === 'mock' || v === 'real'
  );
  // 旧值迁移. localStorage 里 'mock' → 'local', 'real' → 'llm'.
  const runtimeMode: RuntimeMode =
    runtimeModeStored === 'mock' ? 'local' : runtimeModeStored === 'real' ? 'llm' : runtimeModeStored;
  const apiKey = readSession<string | null>(
    STORAGE_KEYS.apiKey ?? 'sf-api-key',
    null
  );
  return {
    ...initialState,
    theme: effectiveTheme,
    locale,
    recentSearches: recent,
    runtimeMode: runtimeMode,
    hasApiKey: !!apiKey,
    settingsCollapsed: readStorage<boolean>('sf-settings-collapsed', false),
  };
})();

const listeners = new Set<() => void>();

function notify(): void {
  for (const l of listeners) l();
}

export function getState(): State {
  return state;
}

export function setState(updater: Partial<State> | ((s: State) => Partial<State>)): void {
  const patch = typeof updater === 'function' ? updater(state) : updater;
  state = { ...state, ...patch };
  // Side effects: persist specific fields when they change
  if ('theme' in patch) {
    writeStorage(STORAGE_KEYS.theme ?? 'sf-theme', state.theme);
    applyTheme(state.theme);
  }
  if ('recentSearches' in patch) {
    writeStorage(STORAGE_KEYS.recentSearches ?? 'sf-recent-searches', state.recentSearches);
  }
  if ('runtimeMode' in patch) {
    writeStorage(STORAGE_KEYS.runtimeMode ?? 'sf-runtime-mode', state.runtimeMode);
  }
  if ('locale' in patch) {
    writeStorage(STORAGE_KEYS.locale ?? 'sf-locale', state.locale);
  }
  notify();
}

// Initialize theme on module load
applyTheme(state.theme);

// ===== Hook =====

export function useStore<T>(selector: (s: State) => T): T {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => { listeners.delete(l); };
    },
    () => selector(state),
    () => selector(initialState)
  );
}

// ===== SSE engine (Phase 2) =====

interface SSEDoneEvent { event: 'done'; result: SearchResult; elapsed?: number; cached?: boolean; }
interface SSEErrorEvent { event: 'error'; code?: string; message: string; }
interface SSEStartedEvent { event: 'started'; cached?: boolean; max_iter?: number; }
interface SSENodeEvent {
  event: 'node_complete';
  node: string;
  step: number;
  elapsed: number;
  iteration?: number;
  cost_usd?: number;
  tokens?: number;
}
interface SSEBudgetExceededEvent {
  event: 'budget_exceeded';
  cost_usd?: number;
  budget_usd?: number;
  node?: string;
  message?: string;
}
interface SSEGraphSnapshotEvent {
  event: 'graph_snapshot';
  iteration: number;
  graph: any;
  node_count: number;
  link_count: number;
}
interface SSENodeThinkingEvent {
  event: 'node_thinking';
  node: string;
  step: number;
  messages: string[];
}

type SSEEvent =
  | SSEStartedEvent
  | SSENodeEvent
  | SSEDoneEvent
  | SSEErrorEvent
  | SSEBudgetExceededEvent
  | SSEGraphSnapshotEvent
  | SSENodeThinkingEvent;

const NODE_NAME_TO_STEP: Record<string, number> = {
  query_decompose: 0,
  search: 1,
  expand_citations: 2,
  rank: 3,
  refine: 4,
  synthesize: 5,
  build_graph: 6,
  track_cost: 7,
};

let sseAbort: AbortController | null = null;
let fallbackTimer: ReturnType<typeof setInterval> | null = null;
let fallbackStart = 0;
let requestId: string | null = null;
let genCounter = 0;

function clearFallback() {
  if (fallbackTimer) { clearInterval(fallbackTimer); fallbackTimer = null; }
}

function dispatchSSE(payload: SSEEvent): void {
  switch (payload.event) {
    case 'started':
      setState({ events: [], graphSnapshots: [], nodeThinking: {}, elapsed: 0 });
      break;
    case 'node_complete': {
      const stepIdx = NODE_NAME_TO_STEP[payload.node];
      const ev: NodeEvent = {
        node: payload.node,
        step: typeof stepIdx === 'number' ? stepIdx : 0,
        status: 'completed',
        cost_usd: payload.cost_usd,
        tokens: payload.tokens,
        elapsed: payload.elapsed,
        iteration: payload.iteration,
      };
      setState((s) => ({
        events: [...s.events, ev],
        elapsed: payload.elapsed ?? s.elapsed,
      }));
      break;
    }
    case 'node_thinking':
      // R10.5.55: 增量 append 而非覆盖. 后端 on_chain_end 时 emit 该节点所有
      // 已累积的 messages; 若同一节点 emit 多次 (R11+ 真流式), 我们只取
      // 新增部分 append. 当前用 seenStepsRef 替代 ref-tracking 简单方案:
      // 用 payload.messages.length > 当前长度时, 取新增部分.
      setState((s) => {
        const existing = s.nodeThinking[payload.node] || [];
        const incoming = payload.messages || [];
        const delta =
          incoming.length > existing.length ? incoming.slice(existing.length) : incoming;
        return {
          nodeThinking: {
            ...s.nodeThinking,
            [payload.node]: [...existing, ...delta],
          },
        };
      });
      break;
    case 'graph_snapshot':
      setState((s) => ({
        graphSnapshots: [
          ...s.graphSnapshots,
          {
            iteration: payload.iteration,
            graph: payload.graph,
            node_count: payload.node_count,
            link_count: payload.link_count,
          },
        ],
      }));
      break;
    case 'budget_exceeded': {
      const be: BudgetExceeded = {
        cost_usd: payload.cost_usd ?? 0,
        budget_usd: payload.budget_usd ?? 0,
        message: payload.message,
        node: payload.node,
      };
      setState({
        budgetExceeded: be,
        error: `成本已达 $${be.cost_usd.toFixed(4)} >= 预算 $${be.budget_usd.toFixed(2)}。点击「retry with $X」一键重试。`,
        loading: false,
      });
      break;
    }
    case 'error':
      setState({ error: payload.message || '搜索失败', loading: false });
      break;
    case 'done': {
      // 回填 recent search 的 source 字段
      const rm = (payload.result as any)?.runtime_mode as string | undefined;
      const newSource: RecentEntry['source'] =
        rm === 'llm' ? 'real' : rm === 'local' ? 'local' : 'unknown';
      setState((s) => {
        const nextRecent = s.recentSearches.map((e) =>
          e.query === s.lastSubmittedQuery ? { ...e, source: newSource } : e
        );
        return {
          result: payload.result,
          elapsed: payload.elapsed ?? s.elapsed,
          loading: false,
          recentSearches: nextRecent,
        };
      });
      break;
    }
  }
}

async function runSSE(
  query: string,
  budget: number,
  maxIter: number,
  provider: string | undefined,
  paperMin = 5,
  paperMax = 10,
): Promise<void> {
  const myGen = genCounter;
  const params: Record<string, string> = {
    q: query,
    budget: String(budget),
    max_iter: String(maxIter),
    paper_min: String(paperMin),
    paper_max: String(paperMax),
  };
  if (provider) params.provider = provider;

  const url = `/api/v1/search/stream?` + new URLSearchParams(params).toString();
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
    'Cache-Control': 'no-cache',
  };
  const apiKey = getApiKey();
  if (apiKey) headers['X-API-Key'] = apiKey;

  sseAbort = new AbortController();
  let resp: Response;
  try {
    resp = await fetch(url, { headers, signal: sseAbort.signal });
  } catch (e: any) {
    if (myGen !== genCounter) return;
    setState({ error: `网络错误: ${e?.message || 'fetch 失败'}`, loading: false });
    return;
  }
  if (!resp.ok) {
    if (myGen !== genCounter) return;
    if (resp.status === 401) {
      setState({
        error: '未认证: 请先 Sign in 拿 API Key (或在 .env 设 OPEN_MODE=true)',
        loading: false,
      });
    } else if (resp.status === 429) {
      setState({ error: '请求过于频繁, 请稍后重试', loading: false });
    } else {
      setState({ error: `后端返回 ${resp.status} ${resp.statusText}`, loading: false });
    }
    return;
  }
  if (!resp.body) {
    if (myGen !== genCounter) return;
    setState({ error: '后端响应无 body', loading: false });
    return;
  }

  const rid = resp.headers.get('X-Request-ID');
  if (rid) requestId = rid;

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  clearFallback();

  try {
    while (true) {
      if (myGen !== genCounter) break;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > 1_000_000) {
        throw new Error('SSE buffer overflow (>1MB)');
      }
      const events = buffer.split('\n\n');
      buffer = events.pop() ?? '';
      for (const ev of events) {
        if (myGen !== genCounter) break;
        const dataLine = ev.split('\n').find((l) => l.startsWith('data: '));
        if (!dataLine) continue;
        try {
          const payload = JSON.parse(dataLine.slice(6)) as SSEEvent;
          if (payload?.event) dispatchSSE(payload);
        } catch {
          /* ignore non-JSON */
        }
      }
    }
  } catch (e: any) {
    if (myGen !== genCounter) return;
    if (e?.name !== 'AbortError') {
      setState({ error: `流读取错误: ${e?.message || 'unknown'}` });
    }
  } finally {
    try { reader.cancel(); } catch { /* ignore */ }
    if (myGen === genCounter) {
      clearFallback();
      // Note: done/error/budget_exceeded 自行 set loading=false
    }
  }
}

// ===== Action helpers (typed) =====

export const actions = {
  // Raw setter for advanced use cases (Phase 1 cancelSearch placeholder)
  setState,
  setView(view: ViewId): void { setState({ currentView: view }); },
  setTheme(theme: ThemeId): void { setState({ theme }); },
  setRuntimeMode(mode: RuntimeMode): void { setState({ runtimeMode: mode }); },
  setLocale(locale: Locale): void { setState({ locale }); },
  setApiKey(key: string | null): void {
    writeSession(STORAGE_KEYS.apiKey ?? 'sf-api-key', key);
    setState({ hasApiKey: !!key });
  },
  setUser(user: User | null): void { setState({ user }); },
  openCommandPalette(): void { setState({ commandPaletteOpen: true }); },
  closeCommandPalette(): void { setState({ commandPaletteOpen: false }); },
  openAuthDialog(): void { setState({ authDialogOpen: true }); },
  closeAuthDialog(): void { setState({ authDialogOpen: false }); },
  toggleSettingsCollapsed(): void {
    setState((s) => ({ settingsCollapsed: !s.settingsCollapsed }));
    try { localStorage.setItem('sf-settings-collapsed', JSON.stringify(!getState().settingsCollapsed)); } catch { /* ignore */ }
  },
  openChangelog(): void { setState({ changelogOpen: true }); },
  closeChangelog(): void { setState({ changelogOpen: false }); },
  openCompareDrawer(): void { setState({ compareDrawerOpen: true }); },
  closeCompareDrawer(): void { setState({ compareDrawerOpen: false }); },
  toggleNodeExpand(nodeId: string | null): void {
    setState({
      expandedNodeId: state.expandedNodeId === nodeId ? null : nodeId,
    });
  },
  // ===== Search actions (Phase 2) =====
  setQuery(query: string): void {
    setState({ query });
  },
  async search(
    query: string,
    budget = 2.0,
    maxIter = 3,
    provider?: string,
    paperMin = 5,
    paperMax = 10,
  ): Promise<void> {
    const trimmed = query.trim();
    if (!trimmed) {
      setState({ error: '请输入研究问题' });
      return;
    }
    setState({
      lastQuery: trimmed,
      lastSubmittedQuery: trimmed,
      error: null,
      budgetExceeded: null,
      result: null,
      selectedPaperId: null,
      selectedPaperIds: [],
      events: [],
      graphSnapshots: [],
      nodeThinking: {},
    });
    // 加到 recent searches (LRU, top 5, source 暂 unknown)
    setState((s) => {
      const placeholder: RecentEntry = { query: trimmed, source: 'unknown', ts: Date.now() };
      const next = [
        placeholder,
        ...s.recentSearches.filter((e) => e.query !== trimmed),
      ].slice(0, 5);
      return { recentSearches: next };
    });
    // bump generation
    genCounter += 1;
    fallbackStart = Date.now();
    clearFallback();
    fallbackTimer = setInterval(() => {
      setState({ elapsed: (Date.now() - fallbackStart) / 1000 });
    }, 200);
    setState({ loading: true });
    await runSSE(trimmed, budget, maxIter, provider, paperMin, paperMax);
  },
  cancelSearch(): void {
    genCounter += 1;
    if (sseAbort) {
      sseAbort.abort();
      sseAbort = null;
    }
    clearFallback();
    const rid = requestId;
    requestId = null;
    if (rid) {
      // 后端 cancel via API
      fetch('/api/v1/search/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: rid }),
      }).catch(() => { /* ignore */ });
    }
    setState({ loading: false });
  },
  resetSearch(): void {
    genCounter += 1;
    if (sseAbort) {
      sseAbort.abort();
      sseAbort = null;
    }
    clearFallback();
    requestId = null;
    setState({
      result: null,
      error: null,
      lastQuery: '',
      lastSubmittedQuery: '',
      elapsed: 0,
      loading: false,
      events: [],
      graphSnapshots: [],
      nodeThinking: {},
      budgetExceeded: null,
      selectedPaperId: null,
      selectedPaperIds: [],
    });
  },
  selectPaper(id: string | null, additive: boolean = false): void {
    if (!id) {
      setState({ selectedPaperId: null });
      return;
    }
    if (additive) {
      const ids = state.selectedPaperIds;
      if (ids.includes(id)) {
        setState({
          selectedPaperIds: ids.filter((x) => x !== id),
          selectedPaperId: state.selectedPaperId === id ? null : state.selectedPaperId,
        });
      } else if (ids.length >= 2) {
        // Replace oldest selection
        setState({ selectedPaperIds: [...ids.slice(1), id], selectedPaperId: id });
      } else {
        setState({
          selectedPaperIds: [...ids, id],
          selectedPaperId: id,
        });
      }
    } else {
      setState({ selectedPaperId: id });
    }
  },
  clearSelection(): void {
    setState({ selectedPaperId: null, selectedPaperIds: [] });
  },
};

// Helper for getting papers from current result with proper types
export function getPapers(): Paper[] {
  return state.result?.ranked_papers ?? [];
}