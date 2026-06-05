import { useState, useCallback, useEffect, useRef } from 'react';
import type { SearchResult } from '../types';
import { searchPapers } from '../services/api';

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

type SSEEvent = SSEStartedEvent | SSENodeEvent | SSEDoneEvent | SSEErrorEvent;

export function useSearch() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [lastQuery, setLastQuery] = useState('');
  const [currentStep, setCurrentStep] = useState(0);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [usingFallback, setUsingFallback] = useState(false);

  const esRef = useRef<EventSource | null>(null);
  const fallbackTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fallbackStartRef = useRef<number>(0);
  // H6: generation counter — bumped on every search / reset.
  // Captured per-call (`myGen`) so a late SSE event from a previous search
  // (or a reset search) is recognized as stale and ignored.
  const genRef = useRef<number>(0);

  // 启动假进度（fallback 用）。仅在 EventSource 不可用时启用。
  const startFallbackProgress = useCallback(() => {
    setUsingFallback(true);
    setCurrentStep(0);
    setElapsedSec(0);
    fallbackStartRef.current = Date.now();
    if (fallbackTimerRef.current) clearInterval(fallbackTimerRef.current);
    fallbackTimerRef.current = setInterval(() => {
      const sec = (Date.now() - fallbackStartRef.current) / 1000;
      setElapsedSec(sec);
      const step = Math.min(7, Math.floor(sec / 2));
      setCurrentStep(step);
    }, 250);
  }, []);

  const stopFallbackProgress = useCallback(() => {
    setUsingFallback(false);
    if (fallbackTimerRef.current) {
      clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
  }, []);

  // 卸载时清理
  useEffect(() => {
    return () => {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (fallbackTimerRef.current) {
        clearInterval(fallbackTimerRef.current);
        fallbackTimerRef.current = null;
      }
    };
  }, []);

  const searchWithSSE = useCallback(
    (query: string, budget: number, maxIter: number) => {
      // 重置
      setError(null);
      setResult(null);
      setLastQuery(query);
      setCurrentStep(0);
      setElapsedSec(0);
      setUsingFallback(false);

      // H5: 关闭旧 EventSource（在 new EventSource 之前显式关掉，避免短暂重叠）
      if (esRef.current) {
        try { esRef.current.close(); } catch { /* ignore */ }
        esRef.current = null;
      }

      // 先启动假进度（EventSource 第一次 message 到达后立即覆盖成真实进度）
      // 这样 SSE 连接未建立的几百 ms 内 UI 不会卡在 0
      setCurrentStep(0);
      fallbackStartRef.current = Date.now();
      if (fallbackTimerRef.current) clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = setInterval(() => {
        const sec = (Date.now() - fallbackStartRef.current) / 1000;
        setElapsedSec(sec);
        // SSE 没消息前，最多多推 1 步（"查询分解"），避免假进度走太远
        const step = Math.min(1, Math.floor(sec / 2));
        setCurrentStep(step);
      }, 250);

      // 构造 SSE URL。Vite dev proxy: /api -> http://127.0.0.1:8000
      const url = `/api/search/stream?` + new URLSearchParams({
        q: query,
        budget: String(budget),
        max_iter: String(maxIter),
      }).toString();

      let es: EventSource;
      try {
        es = new EventSource(url);
      } catch (e: any) {
        // 浏览器不支持 EventSource — 切到完整假进度 + 老 /search 接口
        stopFallbackProgress();
        startFallbackProgress();
        return searchPapers(query, budget, maxIter)
          .then((data) => {
            setResult(data);
            setCurrentStep(PIPELINE_STEPS.length - 1);
          })
          .catch((err: any) => setError(err?.message || '搜索失败'))
          .finally(() => {
            stopFallbackProgress();
          });
      }

      esRef.current = es;
      // H5: 闭包内捕获本次 EventSource — cleanup / handler 通过这个常量引用，
      // 不再读取 esRef.current（动态引用指向最新连接），避免跨连接误关。
      const myEs = es;
      // H6: 闭包内捕获本次 generation — 任何后续 search/reset 都会 bump genRef，
      // 这里的 myGen 仍持有旧值，handler 通过不等式检测出"陈旧事件"并直接 return。
      const myGen = genRef.current;
      let receivedAnyEvent = false;
      let stopped = false;

      const cleanup = () => {
        if (stopped) return;
        stopped = true;
        // H5: 关的是本次创建的那条 es（闭包常量），不是 esRef.current 当前指向的对象
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
      };

      es.onopen = () => {
        // 连接建立，不做处理
      };

      es.onmessage = (ev) => {
        // H5: 陈旧事件 — 这条 es 已被新 search 替换为 esRef.current 的最新值
        if (myEs !== esRef.current) return;
        // H6: 陈旧事件 — 用户已 reset / 启动新 search，genRef 已被 bump
        if (myGen !== genRef.current) return;
        receivedAnyEvent = true;
        // 收到第一条真实事件，关闭"乐观"假进度
        if (fallbackTimerRef.current) {
          clearInterval(fallbackTimerRef.current);
          fallbackTimerRef.current = null;
        }
        let payload: SSEEvent | null = null;
        try {
          payload = JSON.parse(ev.data) as SSEEvent;
        } catch {
          return; // 忽略非 JSON 行
        }
        if (!payload || !payload.event) return;

        if (payload.event === 'started') {
          // 服务端确认开始
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
          cleanup();
          setLoading(false);
        }
      };

      es.onerror = () => {
        // EventSource 出错：若从未收到任何事件（连接本身就失败），回退到 /search + 假进度
        if (!receivedAnyEvent) {
          cleanup();
          stopFallbackProgress();
          startFallbackProgress();
          searchPapers(query, budget, maxIter)
            .then((data) => {
              setResult(data);
              setCurrentStep(PIPELINE_STEPS.length - 1);
            })
            .catch((err: any) => setError(err?.message || '搜索失败'))
            .finally(() => {
              stopFallbackProgress();
              setLoading(false);
            });
        } else {
          // 已经收到过事件，说明中途断流 — 直接失败
          cleanup();
          setError('连接中断，请重试');
          setLoading(false);
        }
      };
    },
    [startFallbackProgress, stopFallbackProgress]
  );

  const search = useCallback(
    async (query: string, budget = 2.0, maxIter = 3) => {
      if (!query.trim()) {
        setError('请输入研究问题');
        return;
      }
      setLoading(true);
      try {
        await searchWithSSE(query, budget, maxIter);
      } catch (e: any) {
        setError(e?.message || '搜索失败');
        setLoading(false);
      }
    },
    [searchWithSSE]
  );

  const reset = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (fallbackTimerRef.current) {
      clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
    setResult(null);
    setError(null);
    setLastQuery('');
    setCurrentStep(0);
    setElapsedSec(0);
    setUsingFallback(false);
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
    usingFallback,
  };
}
