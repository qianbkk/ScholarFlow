import type { SearchResult } from '../types';

// R10.5 Fix-P0-vite-proxy: 改用 /api/v1 前缀 (跟后端 R10.5 Fix-P2-4-Audit-diff
// 引入的版本化路由一致). 旧 /api 在 vite proxy 修复后仍会 404 (后端只有 /api/v1/*
// 和裸 /* alias, 没有 /api/* 路径), useSearch.ts 已经用 /api/v1, 这里同步过来.
const API_BASE = '/api/v1';

// R10.5.28 (CG.txt §1 P1 #4): API Key 存储降级 localStorage → sessionStorage.
// R10.5.28: setApiKey / getApiKey 改成 module exports (useSearch.ts 直接调).
// R10.5.28: 重置闲置计时器 _resetIdleTimer 也 export 出来给 useSearch 用 (let _idleTimer 在模块内).
// localStorage 存 API key 是 XSS 放大器: 任何第三方 script 注入 (CDN 投毒 /
// 依赖链妥协 / 浏览器扩展) 都能 exfiltrate, 而且 key 永久有效, 关浏览器也
// 不会自动失效. 改 sessionStorage 后: 标签页关闭即失, XSS 偷走后攻击窗口
// 缩短到当前标签页生命周期 (典型 10-30 分钟), 用户的物理接触 (关浏览器)
// 直接让 key 失效.
//
// 已知不能完全防御的情况:
//   - 浏览器扩展 (可读 sessionStorage 跨域)
//   - 同标签页内运行中的恶意 JS (CSP 已加, 内联 script 全禁, 攻击面窄)
//   - DevTools 物理访问
// 进一步缓解: (1) CSP 已加 (R10.5.21); (2) DOMPurify 在 ReportPanel 过滤;
// (3) /auth/revoke 端点用户可一键轮换 key (R10.5.28); (4) 自动闲置超时
// 30 分钟 (setTimeout-based, 关浏览器后失效).
// R11+ 计划: 改用 HttpOnly+SameSite=Strict cookie + CSRF token.
const STORED_KEY = 'sf-api-key';
const IDLE_TIMEOUT_MS = 30 * 60 * 1000;  // 30 分钟无活动自动清 key

// R10.5.28: 闲置自动清 key. 模块级 ref, 每次 setApiKey 重置定时器.
let _idleTimer: ReturnType<typeof setTimeout> | null = null;
function _resetIdleTimer(): void {
  if (_idleTimer) clearTimeout(_idleTimer);
  _idleTimer = setTimeout(() => {
    // 30 分钟无活动, 自动清 key. 用户重新打开标签页就要重新登录.
    try { sessionStorage.removeItem(STORED_KEY); } catch { /* ignore */ }
  }, IDLE_TIMEOUT_MS);
}

export function getApiKey(): string | null {
  try {
    // 优先 sessionStorage, 兼容旧 localStorage (一次性迁移, R10.5.28)
    const fromSession = sessionStorage.getItem(STORED_KEY);
    if (fromSession) return fromSession;
    const fromLocal = localStorage.getItem(STORED_KEY);
    if (fromLocal) {
      // 一次性迁移: 旧 localStorage key 挪到 sessionStorage
      try {
        sessionStorage.setItem(STORED_KEY, fromLocal);
        localStorage.removeItem(STORED_KEY);
      } catch { /* ignore */ }
      _resetIdleTimer();
      return fromLocal;
    }
    return null;
  } catch {
    return null;
  }
}

export function setApiKey(key: string | null): void {
  try {
    if (key) {
      sessionStorage.setItem(STORED_KEY, key);
      // 顺手清 localStorage 旧值, 防多 tab 复用
      try { localStorage.removeItem(STORED_KEY); } catch { /* ignore */ }
      _resetIdleTimer();
    } else {
      sessionStorage.removeItem(STORED_KEY);
      try { localStorage.removeItem(STORED_KEY); } catch { /* ignore */ }
      if (_idleTimer) {
        clearTimeout(_idleTimer);
        _idleTimer = null;
      }
    }
  } catch {
    // sessionStorage 不可用 (隐私模式) 静默
  }
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  // R10.5.29 (code-review): 每次 API 调用都 touch timer, 避免"用户活跃使用却被登出".
  // 旧版 _resetIdleTimer 只在 setApiKey 调用, 长会话后 30 分钟到 → key 被清 →
  // 401, 用户被突然登出. 改进: 任何 authHeaders() 调用 (即任何 /api/v1/* fetch)
  // 都视作"用户活动", 重置 30 分钟窗口.
  if (key) _resetIdleTimer();
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

// ===== R10.5.20: Runtime Mode 切换 (前端 UI 控制 mock/real) =====
export type RuntimeMode = 'mock' | 'real';

export interface RuntimeModeInfo {
  mode: RuntimeMode;
  source: 'runtime' | 'env';  // 'runtime' = 前端切了, 'env' = env LLM_MOCK/API_MOCK 兜底
}

export async function fetchRuntimeMode(): Promise<RuntimeModeInfo> {
  const resp = await fetch(`${API_BASE}/admin/runtime-mode`, {
    headers: { ...authHeaders() },
  });
  if (!resp.ok) throw new Error(`fetchRuntimeMode failed: ${resp.status}`);
  return resp.json();
}

export async function setRuntimeMode(mode: RuntimeMode): Promise<RuntimeModeInfo> {
  const resp = await fetch(`${API_BASE}/admin/runtime-mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ mode }),
  });
  if (!resp.ok) throw new Error(`setRuntimeMode failed: ${resp.status}`);
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
