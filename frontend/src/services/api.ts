import type { SearchResult } from '../types';

// Vite dev proxy 走 /api 前缀；生产环境可直接指向后端
const API_BASE = '/api';

export async function searchPapers(
  query: string,
  budget: number = 2.0,
  maxIterations: number = 3
): Promise<SearchResult> {
  const resp = await fetch(`${API_BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, budget, max_iterations: maxIterations }),
  });
  if (!resp.ok) {
    let detail = 'Search failed';
    try {
      const err = await resp.json();
      detail = err.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return resp.json();
}

export async function healthCheck(): Promise<{ status: string; service: string; version: string }> {
  const resp = await fetch(`${API_BASE}/health`);
  if (!resp.ok) throw new Error('Health check failed');
  return resp.json();
}
