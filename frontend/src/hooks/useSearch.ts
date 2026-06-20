import { useState, useCallback, useEffect, useRef } from 'react';
import type { SearchResult } from '../types';
import { searchPapers, fetchMe, getApiKey } from '../services/api';
import {
  readLocalStorage,
  writeLocalStorage,
} from '../lib/useLocalStorage';
// R10.5.51 cleanup: 改用 STORAGE_KEYS 中央化. 详见 BACKLOG.md D 节.
import { STORAGE_KEYS } from '../lib/storageKeys';

// 8 节点流水线步骤（用于进度反馈）
// key 与后端 NODE_NAME_TO_STEP 映射保持一致（前端展示用）
const PIPELINE_STEPS = [
  { key: 'decomposing',     label: '查询分解',   emoji: '①' },
  { key: 'searching',       label: '双源检索',   emoji: '②' },
  { key: 'expanding',       label: '引文扩展',   emoji: '③' },
  { key: 'ranking',         label: '三维排序',   emoji: '④' },
  { key: 'checking_refine', label: '自适应改写', emoji: '⑤' },
  { key: 'synthesizing',    label: '综述生成',   emoji: '⑥' },
  { key: 'building_graph',  label: '图谱构建',   emoji: '⑦' },
  { key: 'tracking_cost',   label: '成本汇总',   emoji: '⑧' },
];

// 后端 LangGraph 节点名 -> 前端展示步骤 index
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

interface SSEDoneEvent {
  event: 'done';
  result: SearchResult;
  elapsed?: number;
  cached?: boolean;
}

interface SSEErrorEvent {
  event: 'error';
  code?: string;
  message: string;
}

interface SSEStartedEvent {
  event: 'started';
  cached?: boolean;
  max_iter?: number;
}

interface SSENodeEvent {
  event: 'node_complete';
  node: string;
  step: number;
  elapsed: number;
  iteration?: number;
}

// Round 4 U1: 节点级预算硬停止事件 (P0-1)
interface SSEBudgetExceededEvent {
  event: 'budget_exceeded';
  cost_usd?: number;
  budget_usd?: number;
  node?: string;
  message?: string;
}

// R10.5.28: graph_snapshot 事件类型, 后端 build_graph 节点完成后推送
// (R10.5 SSE /search/stream 已经实现, 在 backend/main.py search_stream 路径里).
interface SSEGraphSnapshotEvent {
  event: 'graph_snapshot';
  iteration: number;
  graph: any;  // CitationGraph
  node_count: number;
  link_count: number;
}

type SSEEvent = SSEStartedEvent | SSENodeEvent | SSEDoneEvent | SSEErrorEvent | SSEBudgetExceededEvent | SSEGraphSnapshotEvent;

// R10.5.28: Holographic 集成类型 — 喂给 CockpitDashboard / EvolutionSlider.
// 跟 CockpitDashboard.tsx 里 NodeEvent / GraphSnapshot 接口保持一致
// (它是 props 类型, 不 export, 这里我们本地定义相同的形状).
export interface NodeEvent {
  node: string;
  step: number;
  status: 'running' | 'completed';
  model?: string;
  cost_usd?: number;
  tokens?: number;
  elapsed: number;
  // iteration 也带上, EvolutionSlider 用
  iteration?: number;
}

export interface GraphSnapshot {
  iteration: number;
  graph: any;
  node_count: number;
  link_count: number;
}

// type SSEEvent 已在文件顶部 (line ~80) R10.5.28 扩展为含 GraphSnapshotEvent

// R10.5.5 交互升级: 最近搜索 localStorage 持久化
// 5 条上限, LRU 替换, 用 'sf-recent-searches' 命名空间
// R10.5.9 code-review 落地: 复用 lib/useLocalStorage 的 readLocalStorage/writeLocalStorage,
// 删 4 处重复的 try/parse/filter 样板.
// R10.5.28 (CD.txt 隐性问题): 历史记录分本地 / 真实两路.
//   - 旧 schema: string[] (只有 query)
//   - 新 schema: {query, source: 'local'|'real', ts}[] (CD.txt 修复: 区分 mock 演示 vs 真 API)
//   - 一次性迁移: 旧 string[] 自动转 {query: s, source: 'unknown', ts: 0}
// R10.5.51 cleanup (BACKLOG B-008): key 走 STORAGE_KEYS 中央化.
const RECENT_KEY = STORAGE_KEYS.recentSearches;
const RECENT_MAX = 5;
export type RecentSource = 'local' | 'real' | 'unknown';
export interface RecentEntry {
  query: string;
  source: RecentSource;
  ts: number;  // 毫秒, 排序 / 显示用
}

// R10.5.29 (simplify): 抽 isArrayOf 泛型, 2 个 validator 都用. 之前每个 inline
// 自己写 Array.isArray + every, 重复 2 次.
const isArrayOf = <T>(v: unknown, pred: (x: unknown) => x is T): v is T[] =>
  Array.isArray(v) && v.every(pred);

const isStringArray = (v: unknown): v is string[] =>
  isArrayOf(v, (x): x is string => typeof x === 'string');

function isRecentEntry(v: unknown): v is RecentEntry {
  if (v === null || typeof v !== 'object') return false;
  const e = v as RecentEntry;
  return (
    typeof e.query === 'string' &&
    ['local', 'real', 'unknown'].includes(e.source) &&
    typeof e.ts === 'number'
  );
}
const isRecentEntryArray = (v: unknown): v is RecentEntry[] =>
  isArrayOf(v, isRecentEntry);

function loadRecent(): RecentEntry[] {
  // 优先新 schema
  const v = readLocalStorage<RecentEntry[]>(RECENT_KEY, [], { validate: isRecentEntryArray });
  if (v.length) return v;
  // 一次性迁移: 旧 string[] → 新 schema, source 标 'unknown' (无法判断)
  const legacy = readLocalStorage<string[]>(RECENT_KEY, [], { validate: isStringArray });
  if (legacy.length) {
    const migrated: RecentEntry[] = legacy.map((q) => ({ query: q, source: 'unknown', ts: 0 }));
    // R10.5.30 (D7 P2-8): 旧版 writeLocalStorage 失败时仍 removeItem, 静默丢用户历史.
    // 修: writeLocalStorage 内部已 try/catch, 我们用返回值 (写入字节数) 判成功.
    // 但 lib/useLocalStorage 的 writeLocalStorage 是 void, 所以用 try-catch 包整个迁移:
    // 成功时只写不删, 失败时保留旧数据 + 返回新数据 (用户看到迁移, 下次再试).
    const sliced = migrated.slice(0, RECENT_MAX);
    let writeOk = false;
    try {
      // 旧 impl 内部 try/catch 静默, 我们直接 localStorage.setItem 试一次
      // (跟 writeLocalStorage 等价, 但能 catch)
      localStorage.setItem(RECENT_KEY, JSON.stringify(sliced));
      writeOk = true;
    } catch { /* write failed */ }
    if (writeOk) {
      // 写入成功才删旧 key (旧 localStorage 'sf-recent-searches' 跟 RECENT_KEY
      // 同名, 这里 removeItem 是 noop, 但保留以防未来 schema key 改名)
      return sliced;
    }
    // write 失败: 保留旧 data, 但仍返 migrated (用户能看到迁移后格式)
    return migrated;
  }
  return [];
}

function saveRecent(entries: RecentEntry[]): void {
  writeLocalStorage(RECENT_KEY, entries.slice(0, RECENT_MAX));
}

// R10.5.5 交互升级: 成本超限结构化数据
// 之前 budget_exceeded 只是 setError 字符串, 用户只能修改预算后手动重跑.
// 现在暴露结构化数据 + 建议预算, App.tsx 显示"调高预算"按钮一键重跑.
export interface BudgetExceeded {
  cost_usd: number;
  budget_usd: number;
  message?: string;
  node?: string;
}

export function useSearch() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [lastQuery, setLastQuery] = useState('');
  const [currentStep, setCurrentStep] = useState(0);
  const [elapsedSec, setElapsedSec] = useState(0);
  // R10.5.5: 成本超限结构化数据 + 最近搜索历史
  const [budgetExceeded, setBudgetExceeded] = useState<BudgetExceeded | null>(null);
  const [recentSearches, setRecentSearches] = useState<RecentEntry[]>(loadRecent);
  // R10.5.28 (Holographic 集成): 暴露节点级事件流 + 图谱快照给 CockpitDashboard /
  // EvolutionSlider. 原 CostDashboard 只有 currentStep 标量, 看不到每个节点的成本 /
  // 模型 / tokens. events 是 8 节点流水线的 timeline, 喂给 CockpitDashboard
  // 渲染 8 舱室 + Thought Stream.
  const [events, setEvents] = useState<NodeEvent[]>([]);
  // R10.5.28: 每次 build_graph 节点完成时后端推一个图谱快照, 喂 EvolutionSlider
  // 让用户拖时间轴看图谱生长 (V1 → V2 → V3).
  const [graphSnapshots, setGraphSnapshots] = useState<GraphSnapshot[]>([]);

  // R10.5.9 落地: 移除 esRef/reconnectTimerRef 历史注释 — R10.5.8 code-review
  // 已删两个 ref, 注释没必要每次提醒"已移除". 代码即真相.
  const fallbackTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fallbackStartRef = useRef<number>(0);
  const requestIdRef = useRef<string | null>(null);
  // H6: generation counter — bumped on every search / reset.
  const genRef = useRef<number>(0);
  // R10.5.8 修复: 全局兜底超时, 防 SSE 真死锁 (e.g. 401 / 后端卡死) 90s 无
  // 任何事件时强制报错. search() 启动时 setTimeout, 收首个 SSE 事件后清掉.
  const globalTimeoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const GLOBAL_TIMEOUT_MS = 90_000;
  // R10.5.5: 网络错自动重试 — 1 次尝试, 2s backoff (WIFI 切换 / VPN 重连).
  // R10.5.45 (P0/P1 SSE resilience): 升级到指数退避 (1s, 2s, 4s), max 3 次.
  // 旧: 固定 2s, 1 次 → VPN 重连/慢网络场景下 1 次不够. 升级: 3 次, backoff
  // 翻倍, 给弱网更宽容的恢复窗口.
  const retryCountRef = useRef<number>(0);
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // R10.5.45: 客户端最后收到的 SSE event id. 网络断开重连时, fetch URL
  // 带 ?last_event_id=<n> (后端 query param 接收). 浏览器 fetch 不允许设置
  // Last-Event-ID header (forbidden header name), 走 query param 兼容.
  const lastEventIdRef = useRef<number | null>(null);

  const stopFallbackProgress = useCallback(() => {
    if (fallbackTimerRef.current) {
      clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
    // R10.5.8 code-review 修复: 同步清 globalTimeoutTimer (收到首个 SSE 事件后
    // 兜底超时不再需要, 后续流程有 done/error/budget_exceeded 自行收尾).
    if (globalTimeoutTimerRef.current) {
      clearTimeout(globalTimeoutTimerRef.current);
      globalTimeoutTimerRef.current = null;
    }
  }, []);

  // 卸载时清理
  useEffect(() => {
    return () => {
      // R10.5 Fix-P0: 组件卸载时清理所有 timer 和引用, 防止内存泄漏.
      if (fallbackTimerRef.current) {
        clearInterval(fallbackTimerRef.current);
        fallbackTimerRef.current = null;
      }
      if (globalTimeoutTimerRef.current) {
        clearTimeout(globalTimeoutTimerRef.current);
        globalTimeoutTimerRef.current = null;
      }
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
        retryTimeoutRef.current = null;
      }
    };
  }, []);


  // R10.5 Fix-P0-2.2: fetch + ReadableStream 替代 EventSource.
  // EventSource 浏览器 API 不支持自定义 header, 只能走 ?api_key= query param.
  // 改 fetch + ReadableStream 后, X-API-Key header 走标准 HTTP 头,
  // 不再泄漏到 URL → Nginx/浏览器历史/Referer/CDN 日志.
  // 解析 SSE 格式 (data: {json}\n\n) 自管理, 跟 EventSource 等价.
  //
  // R10.5.8 code-review 修复: 旧注释 "EventSource 路径保留作 fallback" 误导
  // — 当前实现**只走 fetch + ReadableStream**, EventSource 已彻底删除,
  // 不要再去找 EventSource fallback 路径. 抓 X-Request-ID 头给 cancel 用.
  const searchWithFetchStream = useCallback(
    async (
      query: string,
      budget: number,
      maxIter: number,
      provider: string | undefined
    ): Promise<boolean> => {
      const myGen = genRef.current;
      const stoppedRef = { v: false };
      const receivedAnyEvent = { v: false };

      const params: Record<string, string> = {
        q: query,
        budget: String(budget),
        max_iter: String(maxIter),
      };
      if (provider) params.provider = provider;
      // R10.5.45: 断线重连时携带 last_event_id, 让服务端知道客户端已收到的最后位置.
      // 浏览器 fetch 不允许设置 Last-Event-ID header (forbidden header name),
      // 后端 search_stream 端点设计成接收 query param 而非 header.
      // 当前阶段 (R10.5.45) 后端仅 log, 不真续; R11+ 接 LangGraph checkpointer
      // 后才能从 last_event_id 状态续. 这是基础设施.
      if (lastEventIdRef.current !== null) {
        params.last_event_id = String(lastEventIdRef.current);
      }
      // R10.5 P2-4: 用 /api/v1 前缀 (R10.5 Fix-P2-4-Audit-diff 加的).
      // 旧 /api/search/stream 路径 production 部署 (无 vite proxy) 返 404.
      // 旧 /search/stream 路径是 deprecated alias (alias 留在后端).
      // 当前选 /api/v1/search/stream (新版客户端推荐).
      const url = `/api/v1/search/stream?` + new URLSearchParams(params).toString();

      const headers: Record<string, string> = {
        Accept: 'text/event-stream',
        'Cache-Control': 'no-cache',
      };
      // R10.5 Fix-P0-2.2: X-API-Key 通过 header 传, 不再进 URL.
      // 后端 get_current_user 已支持从 Header 读取 (R10.5 Fix-P0-B).
      // R10.5.28 (CG.txt P1 #4): 走 getApiKey() helper 读 sessionStorage
      // (标签页关闭即失, XSS 偷走后攻击窗口缩短). 不再直接 localStorage.
      const apiKey =
        typeof window !== 'undefined'
          ? getApiKey()
          : null;
      if (apiKey) headers['X-API-Key'] = apiKey;

      let resp: Response;
      try {
        resp = await fetch(url, { headers });
      } catch (e: any) {
        if (myGen !== genRef.current) return false;
        setError(`网络错误: ${e?.message || 'fetch 失败'}`);
        setLoading(false);
        return false;
      }
      // 401 / 5xx: 给用户明确错误, 不再让 EventSource 静默死锁
      if (!resp.ok) {
        if (myGen !== genRef.current) return false;
        if (resp.status === 401) {
          setError('未认证: 请先 /auth/login 拿 API Key (或在 .env 设 OPEN_MODE=true)');
        } else if (resp.status === 429) {
          setError('请求过于频繁, 请稍后重试');
        } else {
          setError(`后端返回 ${resp.status} ${resp.statusText}`);
        }
        setLoading(false);
        return false;
      }
      if (!resp.body) {
        if (myGen !== genRef.current) return false;
        setError('后端响应无 body');
        setLoading(false);
        return false;
      }

      // R10.5 Fix-Cancel: 从响应头抓 X-Request-ID, 存到 requestIdRef.
      // 旧实现只声明 requestIdRef 永不赋值 → 取消按钮发的 /api/v1/search/cancel
      // body 永远是 {request_id: null}, 后端查 _in_flight_searches 找不到任务,
      // SSE 流实际没被中断 (只是 UI 隐藏了) → 下次搜索时前一个还在跑,
      // LLM provider 限流 / asyncio 资源争用 → 480s timeout.
      // 修复: 抓 X-Request-ID header (后端 request_id_middleware 写回的),
      //   存到 ref → 取消时 fetch 带上真 id, 后端真能 cancel.
      const rid = resp.headers.get('X-Request-ID');
      if (rid) {
        requestIdRef.current = rid;
      }

      // 收到第一条事件: 关闭乐观假进度
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const dispatchEvent = (payload: SSEEvent): boolean => {
        // R10.5.29 (simplify): 改 switch 而非 5 个 if/else 链. 5 个 case,
        // 默认 return false (流未结束). 返 true 表示流结束 (done/error/budget_exceeded).
        switch (payload.event) {
          case 'started':
            setCurrentStep(0);
            // R10.5.28: 新搜索开始, 清空 events + graphSnapshots 重新累积
            setEvents([]);
            setGraphSnapshots([]);
            return false;
          case 'node_complete': {
            const stepIdx = NODE_NAME_TO_STEP[payload.node];
            if (typeof stepIdx === 'number') setCurrentStep(stepIdx);
            if (typeof payload.elapsed === 'number') setElapsedSec(payload.elapsed);
            // R10.5.28: 累积节点级事件给 CockpitDashboard.
            // 同样的 node_complete 事件再 append 一份 'completed' 状态,
            // CockpitDashboard 内部 useMemo 会用最新的覆盖旧的, 舱室自然显示完成态.
            setEvents((prev) => [
              ...prev,
              {
                node: payload.node,
                step: typeof stepIdx === 'number' ? stepIdx : 0,
                status: 'completed' as const,
                cost_usd: (payload as any).cost_usd,
                tokens: (payload as any).tokens,
                elapsed: payload.elapsed,
                iteration: (payload as any).iteration,
              },
            ]);
            return false;
          }
          // R10.5.28: graph_snapshot 事件 — build_graph 节点完成后推送,
          // 喂给 EvolutionSlider 显示图谱生长时间轴.
          case 'graph_snapshot':
            setGraphSnapshots((prev) => [
              ...prev,
              {
                iteration: payload.iteration,
                graph: payload.graph,
                node_count: payload.node_count,
                link_count: payload.link_count,
              },
            ]);
            return false;
          case 'done':
            setResult(payload.result);
            setCurrentStep(PIPELINE_STEPS.length - 1);
            if (typeof payload.elapsed === 'number') setElapsedSec(payload.elapsed);
            // R10.5.28 (CD.txt 隐性问题修复): 收到 done 时回填这条最近搜索的 source.
            // 后端 result.runtime_mode 字段: "real" | "mock" | "unknown"
            //   - 'real' → RecentSource 'real' (真 LLM + 真学术 API)
            //   - 'mock' → 'local' (本地 mock / fallback)
            //   - 'unknown' → 'unknown' (cache hit, 留原值)
            {
              const rm = (payload.result as any)?.runtime_mode as string | undefined;
              if (rm === 'real' || rm === 'mock') {
                const mappedSource: RecentSource = rm === 'mock' ? 'local' : 'real';
                setRecentSearches((prev) => {
                  const next = prev.map((e) =>
                    e.query === query ? { ...e, source: mappedSource } : e
                  );
                  saveRecent(next);
                  return next;
                });
              }
            }
            return true;
          case 'error':
            setError(payload.message || '搜索失败');
            return true;
          case 'budget_exceeded': {
            // R10.5.5: 暴露结构化数据给 App.tsx 显示"调高预算"一键恢复
            // 之前只 setError 字符串, 用户必须手动改表单. 现在 App 读 budgetExceeded
            // 显示 inline 按钮, 1.5x 当前预算重跑.
            const costUsd = typeof payload.cost_usd === 'number' ? payload.cost_usd : 0;
            const budgetUsd = typeof payload.budget_usd === 'number' ? payload.budget_usd : 0;
            setBudgetExceeded({
              cost_usd: costUsd,
              budget_usd: budgetUsd,
              message: payload.message,
              node: payload.node,
            });
            const costStr = costUsd.toFixed(4);
            const budgetStr = budgetUsd.toFixed(2);
            setError(
              `成本已达 $${costStr} >= 预算 $${budgetStr}。点击右侧「调高预算」一键重试。`
            );
            return true;
          }
          default:
            return false;
        }
      };

      const stopFallback = () => {
        if (fallbackTimerRef.current) {
          clearInterval(fallbackTimerRef.current);
          fallbackTimerRef.current = null;
        }
        if (globalTimeoutTimerRef.current) {
          clearTimeout(globalTimeoutTimerRef.current);
          globalTimeoutTimerRef.current = null;
        }
        // R10.5.29 (code-review): 旧版 stopFallback 漏清 retry timer. 后果:
        // 网络错 2s 后会触发 retry, 但用户在 retry 真正跑之前 cancel 了搜索
        // (或开始新搜索), retry 仍在排队 → 2s 后用旧的 (trimmed, budget, ...)
        // 参数跑一次意外搜索. 现在补上.
        if (retryTimeoutRef.current) {
          clearTimeout(retryTimeoutRef.current);
          retryTimeoutRef.current = null;
        }
      };

      try {
        while (true) {
          if (myGen !== genRef.current) break;
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // SSE 解析 buffer size cap (1MB): 防后端发残缺 \n\n 终止符或 huge
          // event (e.g. 完整 Markdown 报告) 撑爆浏览器内存. 旧实现 O(N²) 拼接.
          if (buffer.length > 1_000_000) {
            throw new Error('SSE buffer overflow (>1MB): 后端事件流异常, 截断');
          }
          // SSE 事件以 \n\n 分隔
          const events = buffer.split('\n\n');
          buffer = events.pop() ?? '';
          for (const ev of events) {
            if (myGen !== genRef.current) break;
            // R10.5.51 (/simplify): ev.split('\n') 只调一次 (Efficiency #11).
            // 旧: 2 次 (一次找 id: 行, 一次找 data: 行) → N 事件 = 2N 次 split.
            // 新: 1 次 split + 2 个变量. 顺手只在 id 实际前进时更新 ref.
            const lines = ev.split('\n');
            let idLine: string | undefined;
            let dataLine: string | undefined;
            for (const l of lines) {
              if (!idLine && l.startsWith('id: ')) idLine = l;
              else if (!dataLine && l.startsWith('data: ')) dataLine = l;
              if (idLine && dataLine) break;  // 早退
            }
            if (idLine) {
              const id = parseInt(idLine.slice(4).trim(), 10);
              if (!isNaN(id) && id >= 0 && id > (lastEventIdRef.current ?? -1)) {
                lastEventIdRef.current = id;  // 单调递增, 不更新就跳过
              }
            }
            if (!dataLine) continue;
            try {
              const payload = JSON.parse(dataLine.slice(6)) as SSEEvent;
              if (!payload || !payload.event) continue;
              if (!receivedAnyEvent.v) {
                receivedAnyEvent.v = true;
                stopFallback();
              }
              const streamDone = dispatchEvent(payload);
              if (streamDone) {
                stoppedRef.v = true;
                return true;
              }
            } catch {
              // 忽略非 JSON 行 (heartbeat 等)
            }
          }
        }
      } catch (e: any) {
        if (myGen !== genRef.current) return false;
        setError(`流读取错误: ${e?.message || 'unknown'}`);
        return false;
      } finally {
        try { reader.cancel(); } catch { /* ignore */ }
        if (myGen === genRef.current) setLoading(false);
      }
      return true;
    },
    [setCurrentStep, setElapsedSec, setResult, setError, setLoading]
  );

  const search = useCallback(
    async (query: string, budget = 2.0, maxIter = 3, provider?: string) => {
      const trimmed = query.trim();
      if (!trimmed) {
        setError('请输入研究问题');
        return;
      }
      // P0-1 fix (深度审计 §P0-1): 漏调 setLastQuery 导致 ReportPanel 永远显示空 query,
      // 重试按钮 fallback 也会拿错. R10.5 SSE 重构时遗漏, 一直未恢复.
      setLastQuery(trimmed);
      setError(null);
      // R10.5.5: 清掉旧的 budgetExceeded 状态, 新搜索给用户干净开始
      setBudgetExceeded(null);
      // R10.5.5: 把这次 query 加到最近搜索 (LRU 去重, 置顶)
      // R10.5.28 (CD.txt 隐性问题修复): source 字段记录这次搜索走 mock / 真实 API.
      //   - 'real'  = 命中后端 result.runtime_mode === 'real' (真 LLM + 真学术 API)
      //   - 'local' = 命中 'mock' (本地演示数据)
      //   - 'unknown' = 网络错 / cache hit 等无法判定的场景
      // 后续 dispatchEvent 'done' 收到 result 时回填 'real' / 'local'.
      // 先记 'unknown' 占位, 不然用户点 ⏱ 时看到空 source 列表.
      setRecentSearches((prev) => {
        const placeholder: RecentEntry = { query: trimmed, source: 'unknown', ts: Date.now() };
        const next = [placeholder, ...prev.filter((e) => e.query !== trimmed)].slice(0, RECENT_MAX);
        saveRecent(next);
        return next;
      });
      // P1-11 fix (深度审计 §P1-11): 假进度计时器在真实 SSE 事件到来前
      // 一直显示 0.0s, 用户以为程序卡死. 启动 setInterval 200ms 推进 elapsedSec.
      // 在第一个真实 SSE 事件触发时由 stopFallbackProgress 清掉.
      fallbackStartRef.current = Date.now();
      if (fallbackTimerRef.current) {
        clearInterval(fallbackTimerRef.current);
      }
      fallbackTimerRef.current = setInterval(() => {
        setElapsedSec((Date.now() - fallbackStartRef.current) / 1000);
      }, 200);
      // R10.5.8 code-review 修复: 启动 90s 全局兜底超时, 防 SSE 真死锁
      // (e.g. 后端卡死/连接挂起) 时用户看 1000s loading. 收到首个 SSE
      // 事件后由 stopFallbackProgress 清掉, 正常流程不受影响.
      //
      // R10.5.19 P0 修复: bump generation 必须在 setTimeout **之前**, 否则
      // 旧代码 `myGenAtStart = N` → setTimeout → 立刻 `genRef.current = N+1`
      // → 90s 后 setTimeout 检查 `N !== N+1` 永远 return, 兜底超时永远不触发.
      // 正确顺序: 先 bump (genRef.current = N+1), 再捕获 (myGenAtStart = N+1),
      // setTimeout 检查 `N+1 !== genRef.current` 才能正确识别"是否有新搜索发生".
      if (globalTimeoutTimerRef.current) {
        clearTimeout(globalTimeoutTimerRef.current);
      }
      // H6: bump generation FIRST, then capture
      genRef.current += 1;
      const myGenAtStart = genRef.current;
      globalTimeoutTimerRef.current = setTimeout(() => {
        // 检查 gen: 用户可能已经在 90s 内启动新搜索, 旧 timer 不应报错
        if (myGenAtStart !== genRef.current) return;
        setError(`请求超时 (${GLOBAL_TIMEOUT_MS / 1000}s 无响应). 请检查网络或调高预算.`);
        setLoading(false);
        genRef.current += 1;  // 防止后续事件污染 result
      }, GLOBAL_TIMEOUT_MS);
      // R10.5.5: 重置重试计数器 — 新搜索允许 max 3 次网络重试
      // R10.5.45: 升级到指数退避 (1s, 2s, 4s)
      retryCountRef.current = 0;
      // R10.5.45: 新搜索重置 lastEventIdRef (上次 session 的 id 已不适用)
      lastEventIdRef.current = null;
      setLoading(true);
      try {
        await searchWithFetchStream(trimmed, budget, maxIter, provider);
      } catch (e: any) {
        const msg = e?.message || '搜索失败';
        // R10.5.45: 网络错自动重试 — 指数退避 (1s, 2s, 4s), max 3 次
        // 判断 "网络错": 错误信息含 fetch/网络/timeout/aborted 等
        // 不重试 budget_exceeded / 401 / 用户取消 / SSE 解析错 (这些是确定性问题)
        const isNetworkError = /fetch failed|networkerror|timeout|aborted|failed to fetch/i.test(msg);
        // R10.5.45: 指数退避表. 3 次: 1s, 2s, 4s. max 3 次足够覆盖
        // VPN 重连/慢网络/服务端重启, 仍失败则让用户看到真错手动重试.
        const RETRY_DELAYS_MS = [1000, 2000, 4000];
        if (isNetworkError && retryCountRef.current < RETRY_DELAYS_MS.length) {
          const delay = RETRY_DELAYS_MS[retryCountRef.current];
          retryCountRef.current += 1;
          // 静默重试, 不向用户报"网络错"再消失, 给个轻提示
          setError(`网络抖动, ${delay / 1000}s 后自动重试 (${retryCountRef.current}/${RETRY_DELAYS_MS.length})…`);
          if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current);
          retryTimeoutRef.current = setTimeout(() => {
            // 重试前清 error, 避免闪烁
            setError(null);
            // 用同一组参数重跑. lastEventIdRef 已保留, 走 query param 续传.
            search(trimmed, budget, maxIter, provider);
          }, delay);
          return;
        }
        setError(msg);
        setLoading(false);
      }
    },
    [searchWithFetchStream]
  );

  // R10.5.5: 主动清除最近搜索
  const clearRecentSearches = useCallback(() => {
    setRecentSearches([]);
    saveRecent([]);
  }, []);

  // R10.5.5: 主动清除 budgetExceeded (用于关闭恢复按钮提示)
  const dismissBudgetExceeded = useCallback(() => {
    setBudgetExceeded(null);
  }, []);

  const reset = useCallback(() => {
    // R10.5 Fix-P0: 清理所有 timer, 防止竞态条件下重复触发.
    if (fallbackTimerRef.current) {
      clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
    if (globalTimeoutTimerRef.current) {
      clearTimeout(globalTimeoutTimerRef.current);
      globalTimeoutTimerRef.current = null;
    }
    // R10.5.5: 重置时清 retry timeout (取消重试中网络)
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }
    // R10.5.45: reset 时也清 lastEventIdRef + retryCountRef, 跟新搜索起点对齐
    lastEventIdRef.current = null;
    retryCountRef.current = 0;
    // H6: bump generation
    genRef.current += 1;
    // R10.5 Fix-P0-RaceCondition: 组件卸载后不再发取消请求, 避免 fetch 在已卸载组件上执行.
    const rid = requestIdRef.current;
    requestIdRef.current = null;
    if (rid) {
      // 使用 AbortController 或简单的 fetch, 不阻塞主线程
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 5000);
      fetch('/api/v1/search/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: rid }),
        signal: controller.signal,
      }).catch((e) => {
        // 忽略取消请求的错误 (组件可能已卸载)
        if (e.name !== 'AbortError') {
          console.warn('[/search/cancel] request failed:', e);
        }
      }).finally(() => clearTimeout(timeout));
    }
    setResult(null);
    setError(null);
    setLastQuery('');
    setCurrentStep(0);
    setElapsedSec(0);
    setLoading(false);
    // R10.5.28: reset 时也清空 events / graphSnapshots, 下次搜索干净起步
    setEvents([]);
    setGraphSnapshots([]);
  }, []);

  return {
    loading,
    error,
    result,
    lastQuery,
    search,
    reset,
    currentStep,
    elapsedSec,
    pipelineSteps: PIPELINE_STEPS,
    // R10.5.5: 新增导出 — 最近搜索 + 成本超限结构化数据 + 关闭
    recentSearches,
    clearRecentSearches,
    budgetExceeded,
    dismissBudgetExceeded,
    // R10.5.28 (Holographic 集成): 节点级事件流 + 图谱快照, 喂 CockpitDashboard / EvolutionSlider
    events,
    graphSnapshots,
  };
}
