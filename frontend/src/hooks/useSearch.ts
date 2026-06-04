import { useState, useCallback, useEffect, useRef } from 'react';
import type { SearchResult } from '../types';
import { searchPapers } from '../services/api';

// 8 节点流水线步骤（用于进度反馈）
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

export function useSearch() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [lastQuery, setLastQuery] = useState('');
  const [currentStep, setCurrentStep] = useState(0);
  const [elapsedSec, setElapsedSec] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 进度模拟：根据耗时推进步骤
  useEffect(() => {
    if (loading) {
      setCurrentStep(0);
      setElapsedSec(0);
      const start = Date.now();
      timerRef.current = setInterval(() => {
        const sec = (Date.now() - start) / 1000;
        setElapsedSec(sec);
        // 每 ~2s 推进一个步骤（最多到 7）
        const step = Math.min(7, Math.floor(sec / 2));
        setCurrentStep(step);
      }, 250);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [loading]);

  const search = useCallback(async (query: string, budget = 2.0, maxIter = 3) => {
    if (!query.trim()) {
      setError('请输入研究问题');
      return;
    }
    setLoading(true);
    setError(null);
    setLastQuery(query);
    try {
      const data = await searchPapers(query, budget, maxIter);
      setResult(data);
      setCurrentStep(PIPELINE_STEPS.length - 1);
    } catch (e: any) {
      setError(e?.message || '搜索失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setResult(null);
    setError(null);
    setLastQuery('');
    setCurrentStep(0);
    setElapsedSec(0);
  }, []);

  return {
    loading, error, result, lastQuery, search, reset,
    currentStep, elapsedSec, pipelineSteps: PIPELINE_STEPS,
  };
}
