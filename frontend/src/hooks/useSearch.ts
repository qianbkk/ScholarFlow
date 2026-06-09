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

  const searchWithSSE = useCallback(
    (query: string, budget: number, maxIter: number, provider?: string) => {
      // 重置
      setError(null);
      setResult(null);
      setLastQuery(query);
      setCurrentStep(0);
      setElapsedSec(0);

      // R10.5 Fix-X1: 生成 request_id, 让 reset 时能告诉后端停哪条 in-flight pipeline
      requestIdRef.current =
        (typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
        ).replace(/-/g, '').slice(0, 12);

      // H5: 关闭旧 EventSource
      if (esRef.current) {
        try { esRef.current.close(); } catch { /* ignore */ }
        esRef.current = null;
      }

      // 乐观假进度
      setCurrentStep(0);
      fallbackStartRef.current = Date.now();
      if (fallbackTimerRef.current) clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = setInterval(() => {
        const sec = (Date.now() - fallbackStartRef.current) / 1000;
        setElapsedSec(sec);
        const step = Math.min(1, Math.floor(sec / 2));
        setCurrentStep((prev) => (prev === step ? prev : step));
      }, 1000);

      const params: Record<string, string> = {
        q: query,
        budget: String(budget),
        max_iter: String(maxIter),
      };
      if (provider) params.provider = provider;
      // R10.5 Fix-P0-2.2: EventSource 不支持自定义 header, 必须走 ?api_key= query param.
      // 不传 api_key 后端 401, 浏览器 EventSource 自动重连 CONNECTING, 永远不发事件 → loading 死锁.
      // 已知风险: api_key 进 URL → Nginx/浏览器历史/Referer 日志泄漏 (P0 审计 2.2).
      // 中期方案 (P0-2): 改 fetch + ReadableStream + X-API-Key header. 当前先传 query param 解死锁.
      const apiKey = (typeof localStorage !== 'undefined' && localStorage.getItem('sf-api-key')) || null;
      if (apiKey) params.api_key = apiKey;
      const url = `/api/search/stream?` + new URLSearchParams(params).toString();

      let es: EventSource;
      const myGen = genRef.current;
      try {
        es = new EventSource(url);
      } catch (e: any) {
        // 浏览器不支持 EventSource — 切到 /search POST + 假进度
        stopFallbackProgress();
        const fbTimer = setInterval(() => {
          const sec = (Date.now() - fallbackStartRef.current) / 1000;
          setElapsedSec(sec);
          const step = Math.min(7, Math.floor(sec / 2));
          setCurrentStep((prev) => (prev === step ? prev : step));
        }, 1000);
        fallbackTimerRef.current = fbTimer;
        searchPapers(query, budget, maxIter, provider)
          .then((data) => {
            if (myGen !== genRef.current) return;
            setResult(data);
            setCurrentStep(PIPELINE_STEPS.length - 1);
          })
          .catch((err: any) => {
            if (myGen !== genRef.current) return;
            setError(err?.message || '搜索失败');
          })
          .finally(() => {
            if (myGen !== genRef.current) return;
            if (fallbackTimerRef.current === fbTimer) {
              clearInterval(fbTimer);
              fallbackTimerRef.current = null;
            }
            setLoading(false);
          });
        return;
      }

      esRef.current = es;
      const myEs = es;
      let receivedAnyEvent = false;
      let stopped = false;
      let fallbackAttempted = false;

      const cleanup = () => {
        if (stopped) return;
        stopped = true;
        if (myEs) {
          try { myEs.close(); } catch { /* ignore */ }
        }
        if (esRef.current === myEs) {
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
        // R10.5 Fix-P0-2.2-b: 清除全局超时兜底 timer
        if (globalTimeoutTimerRef.current) {
          clearTimeout(globalTimeoutTimerRef.current);
          globalTimeoutTimerRef.current = null;
        }
      };

      // R10.5 Fix-P0-2.2-b: 全局兜底超时 (90s).
      // 之前事件级 30s 兜底只在 receivedAnyEvent=true 时启动, 没收到任何事件时
      // (e.g. 401 死锁 / SSE 端点永远不响应) 永远不触发, 加载 1000s 还是 loading.
      // 90s 跟后端 480s 超时对齐: 给真实 LLM 完整跑完 + 后端 SSE 推 done/error 的窗口.
      if (globalTimeoutTimerRef.current) clearTimeout(globalTimeoutTimerRef.current);
      globalTimeoutTimerRef.current = setTimeout(() => {
        if (myGen !== genRef.current) return;
        if (stopped) return;
        // 90s 仍没收到任何事件 → 后端真卡死 (e.g. 401 / 死锁 / 后端崩)
        if (!receivedAnyEvent) {
          cleanup();
          setError('连接超时 (90s 未收到任何响应). 请检查后端服务 / API Key 有效性.');
          setLoading(false);
        }
      }, 90000);

      es.onopen = () => {
        // 连接建立, 不做处理
      };

      es.onmessage = (ev) => {
        // H5/H6: 陈旧事件
        if (myEs !== esRef.current) return;
        if (myGen !== genRef.current) return;
        receivedAnyEvent = true;
        // 收到第一条真实事件, 关闭乐观假进度
        if (fallbackTimerRef.current) {
          clearInterval(fallbackTimerRef.current);
          fallbackTimerRef.current = null;
        }
        let payload: SSEEvent | null = null;
        try {
          payload = JSON.parse(ev.data) as SSEEvent;
        } catch {
          return;
        }
        if (!payload || !payload.event) return;

        if (payload.event === 'started') {
          setCurrentStep(0);
        } else if (payload.event === 'node_complete') {
          const stepIdx = NODE_NAME_TO_STEP[payload.node];
          if (typeof stepIdx === 'number') {
            setCurrentStep(stepIdx);
          }
          if (typeof payload.elapsed === 'number') {
            setElapsedSec(payload.elapsed);
          }
        } else if (payload.event === 'done') {
          setResult(payload.result);
          setCurrentStep(PIPELINE_STEPS.length - 1);
          if (typeof payload.elapsed === 'number') {
            setElapsedSec(payload.elapsed);
          }
          cleanup();
          setLoading(false);
        } else if (payload.event === 'error') {
          setError(payload.message || '搜索失败');
          if (fallbackStartRef.current) {
            setElapsedSec((Date.now() - fallbackStartRef.current) / 1000);
          }
          cleanup();
          setLoading(false);
        } else if (payload.event === 'budget_exceeded') {
          const costStr =
            typeof payload.cost_usd === 'number'
              ? payload.cost_usd.toFixed(4)
              : '?';
          const budgetStr =
            typeof payload.budget_usd === 'number'
              ? payload.budget_usd.toFixed(2)
              : '?';
          setError(
            `成本已达 $${costStr} >= 预算 $${budgetStr}。请降低 max_iterations 或 budget 后重试。`
          );
          if (fallbackStartRef.current) {
            setElapsedSec((Date.now() - fallbackStartRef.current) / 1000);
          }
          cleanup();
          setLoading(false);
          return;
        }
      };

      es.onerror = () => {
        // H5: 陈旧事件
        if (myEs !== esRef.current) return;
        // H6: 陈旧事件
        if (myGen !== genRef.current) return;

        const readyState = myEs.readyState;
        // R10.5 Fix-X1 关键修复: 区分 4 种状态
        // - readyState=0 (CONNECTING): 浏览器 EventSource 自动重连中 (代理 60s 超时/网络抖动)
        //   → 静默等待, 不应误报"连接中断"覆盖 result
        // - readyState=1 (OPEN): 流活跃, 浏览器在重连中(onerror 触发时为 0, 重连成功后回 1)
        // - readyState=2 (CLOSED): 流已关闭, 通常是 cleanup() 主动 close() 或后端报错关闭
        if (readyState === EventSource.CONNECTING) {
          // 浏览器自动重连中, 静默 30s 等重连; 超时则当作真错
          if (receivedAnyEvent) {
            // 已收到过事件, 说明 LLM 已开始响应, 真在跑, 不应报"中断"
            // 设一个 30s 兜底: 如果 30s 内没收到任何事件, 才报"连接中断"
            if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
            reconnectTimerRef.current = setTimeout(() => {
              if (myEs !== esRef.current) return;
              if (myGen !== genRef.current) return;
              if (myEs.readyState === EventSource.CONNECTING) {
                cleanup();
                setError('连接中断, 请重试 (浏览器自动重连超时 30s)');
                setLoading(false);
              }
            }, 30000);
          }
          return;
        }
        if (readyState === EventSource.CLOSED) return;  // 正常关闭
        if (stopped) return;

        // 真出错: 走到这里说明 readyState=OPEN(1) 且非正常关闭
        // 区分"从未收到事件"(SSE 端 401/405 等) vs "中途断流"
        if (!receivedAnyEvent) {
          // R10.5 Fix-X1: 大概率是 401 (OPEN_MODE=false + 没 key) 或 5xx.
          // EventSource 不暴露 HTTP status, 只能走 /auth/me fetch 验证或后端
          // /search/cancel 失败. 先做一次 authMe 检查: 401 立即给用户明确错误.
          if (fallbackAttempted) {
            cleanup();
            setError('连接失败, 请检查后端服务');
            setLoading(false);
            return;
          }
          fallbackAttempted = true;
          cleanup();
          // 用 fetchMe 验证, 区分 401 (无 key) vs 5xx (后端挂了)
          void fetchMe()
            .then((me) => {
              if (myGen !== genRef.current) return;
              if (me === null) {
                setError('未认证: 请先调用 /auth/login 拿 API Key (或在 .env 设 OPEN_MODE=true)');
                setLoading(false);
                return;
              }
              // 有 key 但 SSE 仍失败 — 后端问题, 降级到 /search POST
              const fbTimer = setInterval(() => {
                const sec = (Date.now() - fallbackStartRef.current) / 1000;
                setElapsedSec(sec);
                const step = Math.min(7, Math.floor(sec / 2));
                setCurrentStep((prev) => (prev === step ? prev : step));
              }, 1000);
              fallbackTimerRef.current = fbTimer;
              return searchPapers(query, budget, maxIter, provider)
                .then((data) => {
                  if (myGen !== genRef.current) return;
                  setResult(data);
                  setCurrentStep(PIPELINE_STEPS.length - 1);
                })
                .catch((err: any) => {
                  if (myGen !== genRef.current) return;
                  setError(err?.message || '搜索失败');
                })
                .finally(() => {
                  if (fallbackTimerRef.current === fbTimer) {
                    clearInterval(fbTimer);
                    fallbackTimerRef.current = null;
                  }
                  if (myGen === genRef.current) setLoading(false);
                });
            })
            .catch(() => {
              if (myGen !== genRef.current) return;
              setError('后端服务未连通, 请检查 http://127.0.0.1:8000');
              setLoading(false);
            });
        } else {
          // 已收到事件, 中途断流
          cleanup();
          setError('连接中断, 请重试');
          setLoading(false);
        }
      };
    },
    [stopFallbackProgress]
  );

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
      const url = `/api/search/stream?` + new URLSearchParams(params).toString();

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
      if (!query.trim()) {
        setError('请输入研究问题');
        return;
      }
      // H6: bump generation
      genRef.current += 1;
      setLoading(true);
      try {
        await searchWithFetchStream(query, budget, maxIter, provider);
      } catch (e: any) {
        setError(e?.message || '搜索失败');
        setLoading(false);
      }
    },
    [searchWithSSE]
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
      void fetch('/api/search/cancel', {
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
