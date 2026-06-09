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
      };

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
        await searchWithSSE(query, budget, maxIter, provider);
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
