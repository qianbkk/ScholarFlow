import { useState, useCallback } from 'react';
import type { SearchResult } from '../types';
import { searchPapers } from '../services/api';

export function useSearch() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [lastQuery, setLastQuery] = useState('');

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
  }, []);

  return { loading, error, result, lastQuery, search, reset };
}
