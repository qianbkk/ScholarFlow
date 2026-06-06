import type { SearchResult } from '../types';

// Vite dev proxy 走 /api 前缀；生产环境可直接指向后端
const API_BASE = '/api';

export interface ProviderInfo {
  id: string;
  name: string;
  flagship_model: string;
  fast_model: string;
  has_key: boolean;
}

export interface ProvidersResponse {
  default_provider: string;
  providers: ProviderInfo[];
}

export async function fetchProviders(): Promise<ProvidersResponse> {
  const resp = await fetch(`${API_BASE}/providers`);
  if (!resp.ok) throw new Error('fetch providers failed');
  return resp.json();
}

export async function searchPapers(
  query: string,
  budget: number = 2.0,
  maxIterations: number = 3,
  provider?: string
): Promise<SearchResult> {
  const body: Record<string, unknown> = { query, budget, max_iterations: maxIterations };
  if (provider) body.provider = provider;
  const resp = await fetch(`${API_BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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
