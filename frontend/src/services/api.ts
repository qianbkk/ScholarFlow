import type { SearchResult } from '../types';

// R10.5 Fix-P0-vite-proxy: 改用 /api/v1 前缀 (跟后端 R10.5 Fix-P2-4-Audit-diff
// 引入的版本化路由一致). 旧 /api 在 vite proxy 修复后仍会 404 (后端只有 /api/v1/*
// 和裸 /* alias, 没有 /api/* 路径), useSearch.ts 已经用 /api/v1, 这里同步过来.
const API_BASE = '/api/v1';

// R10.5 Fix-P0-B: API Key 认证. 从 localStorage 读, OPEN_MODE 时后端跳过.
const STORED_KEY = 'sf-api-key';

function getApiKey(): string | null {
  try {
    return localStorage.getItem(STORED_KEY);
  } catch {
    return null;
  }
}

function setApiKey(key: string | null): void {
  try {
    if (key) localStorage.setItem(STORED_KEY, key);
    else localStorage.removeItem(STORED_KEY);
  } catch {
    // localStorage 不可用 (隐私模式) 静默
  }
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { 'X-API-Key': key } : {};
}

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
  // R10 (M-16): default_provider 硬编为 'minimax' (项目所有者偏好).
  // 也允许动态 (后端实际返回哪个就用哪个), 这里保留 string 类型, 由 caller
  // 在运行时判断. 已知合法值: 'kimi' | 'glm' | 'minimax' | 'anthropic' | 'deepseek'.
  default_provider: string;
  // R8.2 修复: 端点列表在 health.py 返回, 旧版前端没有声明类型 (弱类型透传 OK 但
  // 失去 IDE 提示)。加可选字段, 不破坏现有 caller。
  endpoints?: string[];
  providers: ProviderInfo[];
}

export async function fetchProviders(): Promise<ProvidersResponse> {
  const resp = await fetch(`${API_BASE}/providers`, {
    headers: { ...authHeaders() },
  });
  if (!resp.ok) {
    if (resp.status === 401) throw new Error('未认证: 请先登录拿 API Key');
    throw new Error('fetch providers failed');
  }
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
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = 'Search failed';
    try {
      const err = await resp.json();
      detail = err.detail || detail;
    } catch {}
    if (resp.status === 401) detail = '未认证: 请先登录拿 API Key';
    throw new Error(detail);
  }
  return resp.json();
}

export async function healthCheck(): Promise<{ status: string; service: string; version: string }> {
  const resp = await fetch(`${API_BASE}/health`, {
    headers: { ...authHeaders() },
  });
  if (!resp.ok) throw new Error('Health check failed');
  return resp.json();
}

// ===== R10.5 Fix-P0-B: Auth 端点 =====
export interface AuthResponse {
  user_id: string;
  display_name: string;
  api_key: string;
  open_mode: boolean;
}

export interface UserInfo {
  user_id: string;
  display_name: string;
  created_at: number;
  open_mode: boolean;
}

export async function registerOrLogin(
  email: string,
  displayName: string = ''
): Promise<AuthResponse> {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, display_name: displayName }),
  });
  if (!resp.ok) {
    let detail = 'login failed';
    try { detail = (await resp.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  const data: AuthResponse = await resp.json();
  setApiKey(data.api_key);
  return data;
}

export function logout(): void {
  setApiKey(null);
}

export async function fetchMe(): Promise<UserInfo | null> {
  const key = getApiKey();
  if (!key) return null;
  const resp = await fetch(`${API_BASE}/auth/me`, {
    headers: { 'X-API-Key': key },
  });
  if (resp.status === 401) {
    setApiKey(null);
    return null;
  }
  if (!resp.ok) return null;
  return resp.json();
}

export function hasApiKey(): boolean {
  return !!getApiKey();
}
