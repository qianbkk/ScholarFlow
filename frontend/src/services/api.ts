import type { SearchResult } from '../types';

// Vite dev proxy 走 /api 前缀；生产环境可直接指向后端
const API_BASE = '/api';

export interface ProviderInfo {
  id: string;
  name: string;
  flagship_model: string;
  fast_model: string;
  has_key: boolean;
  // R8.2 修复 (reviewer feedback 3.3 - 前后端 schema 漂移):
  // 后端 /providers 实际返回 verified 字段 (True/False/None),
  // 旧版前端丢掉,导致 QueryPanel 模型选择器不能显示"key 失效"红字
  // None = 后端健康检查尚未运行 (启动后 5s 内); False = key 验证失败 (401 等);
  // True = key 验证通过。
  verified?: boolean | null;
}

export interface ProvidersResponse {
  default_provider: string;
  // R8.2 修复: 端点列表在 health.py 返回, 旧版前端没有声明类型 (弱类型透传 OK 但
  // 失去 IDE 提示)。加可选字段, 不破坏现有 caller。
  endpoints?: string[];
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
