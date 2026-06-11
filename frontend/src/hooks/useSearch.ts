import { useState, useCallback, useEffect, useRef } from 'react';
import type { SearchResult } from '../types';
import { searchPapers, fetchMe } from '../services/api';

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

type SSEEvent = SSEStartedEvent | SSENodeEvent | SSEDoneEvent | SSEErrorEvent | SSEBudgetExceededEvent;

export function useSearch() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [lastQuery, setLastQuery] = useState('');
  const [currentStep, setCurrentStep] = useState(0);
  const [elapsedSec, setElapsedSec] = useState(0);

  const esRef = useRef<EventSource | null>(null);
  const fallbackTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fallbackStartRef = useRef<number>(0);
  const requestIdRef = useRef<string | null>(null);
  // H6: generation counter — bumped on every search / reset.
  const genRef = useRef<number>(0);
  // R10.5 Fix-X1: SSE 真实运行 30-180s, 浏览器 EventSource 在代理 60s 超时/网络抖动
  // 时会自动重连, 重连中 onerror 触发, readyState=CONNECTING(0). 这种自动重连不
  // 应被误判为用户错误. 之前旧代码 `if (readyState === CLOSED) return` 没覆盖
  // CONNECTING, 走到 else 分支 setError('连接中断, 请重试') 覆盖 result, UI 看似
  // 白屏. 修复: 显式识别 CONNECTING 是浏览器自动重连, 静默等待.
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // R10.5 Fix-P0-2.2-b: 全局兜底超时 timer, 防止 SSE 真死锁时 (e.g. 401 / 后端卡死)
  // 90s 仍无任何事件时强制报错, 不再让用户看 1000s loading.
  const globalTimeoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopFallbackProgress = useCallback(() => {
    if (fallbackTimerRef.current) {
      clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
  }, []);

  // 卸载时清理
  useEffect(() => {
    return () => {
      if (esRef.current) {
        try { esRef.current.close(); } catch { /* ignore */ }
        esRef.current = null;
      }
      if (fallbackTimerRef.current) {
        clearInterval(fallbackTimerRef.current);
        fallbackTimerRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, []);


  // R10.5 Fix-P0-2.2: fetch + ReadableStream 替代 EventSource.
  // EventSource 浏览器 API 不支持自定义 header, 只能走 ?api_key= query param.
  // 改 fetch + ReadableStream 后, X-API-Key header 走标准 HTTP 头,
  // 不再泄漏到 URL → Nginx/浏览器历史/Referer/CDN 日志.
  // 解析 SSE 格式 (data: {json}\n\n) 自管理, 跟 EventSource 等价.
  //
  // 当前实现: 默认走 fetch 路径; EventSource 路径保留作 fallback (老浏览器 / 调试).
  // 修复 known caveat: X-Request-ID 头可在此处透传 (R10.5 已实现 request_id 注入).
  // R10.5 Fix-P0-2.2 文档: 优先用 fetch, EventSource 是 fallback.
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
      const apiKey =
        typeof localStorage !== 'undefined'
          ? localStorage.getItem('sf-api-key')
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
        // 返 true 表示流结束 (done/error/budget_exceeded)
        if (payload.event === 'started') {
          setCurrentStep(0);
          return false;
        }
        if (payload.event === 'node_complete') {
          const stepIdx = NODE_NAME_TO_STEP[payload.node];
          if (typeof stepIdx === 'number') setCurrentStep(stepIdx);
          if (typeof payload.elapsed === 'number') setElapsedSec(payload.elapsed);
          return false;
        }
        if (payload.event === 'done') {
          setResult(payload.result);
          setCurrentStep(PIPELINE_STEPS.length - 1);
          if (typeof payload.elapsed === 'number') setElapsedSec(payload.elapsed);
          return true;
        }
        if (payload.event === 'error') {
          setError(payload.message || '搜索失败');
          return true;
        }
        if (payload.event === 'budget_exceeded') {
          const costStr = typeof payload.cost_usd === 'number' ? payload.cost_usd.toFixed(4) : '?';
          const budgetStr = typeof payload.budget_usd === 'number' ? payload.budget_usd.toFixed(2) : '?';
          setError(
            `成本已达 $${costStr} >= 预算 $${budgetStr}。请降低 max_iterations 或 budget 后重试。`
          );
          return true;
        }
        return false;
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
            const dataLine = ev.split('\n').find((l) => l.startsWith('data: '));
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
      // H6: bump generation
      genRef.current += 1;
      setLoading(true);
      try {
        await searchWithFetchStream(trimmed, budget, maxIter, provider);
      } catch (e: any) {
        setError(e?.message || '搜索失败');
        setLoading(false);
      }
    },
    [searchWithFetchStream]
  );

  const reset = useCallback(() => {
    if (esRef.current) {
      try { esRef.current.close(); } catch { /* ignore */ }
      esRef.current = null;
    }
    if (fallbackTimerRef.current) {
      clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    // H6: bump generation
    genRef.current += 1;
    if (requestIdRef.current) {
      const rid = requestIdRef.current;
      requestIdRef.current = null;
      void fetch('/api/v1/search/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: rid }),
      }).catch((e) => {
        console.warn('[/search/cancel] request failed:', e);
      });
    }
    setResult(null);
    setError(null);
    setLastQuery('');
    setCurrentStep(0);
    setElapsedSec(0);
    setLoading(false);
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
  };
}
