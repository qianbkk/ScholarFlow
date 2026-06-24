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
// R10.5.51 cleanup: 改用 STORAGE_KEYS 中央化.
import { STORAGE_KEYS } from '../lib/storageKeys';
const STORED_KEY = STORAGE_KEYS.apiKey;
const IDLE_TIMEOUT_MS = 30 * 60 * 1000;  // 30 分钟无活动自动清 key

// R10.5.28: 闲置自动清 key. 模块级 ref, 每次 setApiKey 重置定时器.
let _idleTimer: ReturnType<typeof setTimeout> | null = null;
// R10.5.29 (simplify): 模块级缓存 key, 避免每次 fetch 都读 sessionStorage.
// 之前 authHeaders() 调 getApiKey() 每次都 sessionStorage.getItem, 高频用户
// (50 fetches/min) 浪费 50 次 storage read. 现在 cache 在 module scope, 仅
// setApiKey 调用时失效. _cachedKey 必须跟 _idleTimer 一致处理 timeout 失效.
let _cachedKey: string | null | undefined = undefined;  // undefined = 未初始化
function _resetIdleTimer(): void {
  if (_idleTimer) clearTimeout(_idleTimer);
  _idleTimer = setTimeout(() => {
    // 30 分钟无活动, 自动清 key. 用户重新打开标签页就要重新登录.
    try { sessionStorage.removeItem(STORED_KEY); } catch { /* ignore */ }
    _cachedKey = null;  // 同步 cache, 下次 getApiKey() 才不会返回旧值
  }, IDLE_TIMEOUT_MS);
}

export function getApiKey(): string | null {
  // R10.5.29 (simplify): 走 cache. 只在首次 / 失效时读 storage.
  if (_cachedKey !== undefined) return _cachedKey;
  try {
    // 优先 sessionStorage, 兼容旧 localStorage (一次性迁移, R10.5.28)
    const fromSession = sessionStorage.getItem(STORED_KEY);
    if (fromSession) {
      _cachedKey = fromSession;
      return fromSession;
    }
    const fromLocal = localStorage.getItem(STORED_KEY);
    if (fromLocal) {
      // 一次性迁移: 旧 localStorage key 挪到 sessionStorage
      try {
        sessionStorage.setItem(STORED_KEY, fromLocal);
        localStorage.removeItem(STORED_KEY);
      } catch { /* ignore */ }
      _resetIdleTimer();
      _cachedKey = fromLocal;
      return fromLocal;
    }
    _cachedKey = null;
    return null;
  } catch {
    _cachedKey = null;
    return null;
  }
}

export function setApiKey(key: string | null): void {
  _cachedKey = key;  // R10.5.29 (simplify): 同步 cache, 避免下次 getApiKey() 读 storage
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

/**
 * 纯函数: 返回当前 API Key 的 header 字典 (无副作用).
 * 原实现把 _resetIdleTimer 副作用塞进读函数, 让 "authHeaders" 听起来像
 * 纯函数实际却会重置 30 分钟闲置计时器. 拆 touchAuth() 给调用方显式调.
 */
function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { 'X-API-Key': key } : {};
}

/**
 * 显式标记"用户活跃", 重置 30 分钟闲置计时器.
 * 任何调 authHeaders() 的 fetch 调用方都应紧跟一次 touchAuth(),
 * 避免"用户活跃使用却被登出" (R10.5.29 code-review 修过的回归).
 */
function touchAuth(): void {
  if (getApiKey()) _resetIdleTimer();
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
  touchAuth();
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
  touchAuth();
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
  touchAuth();
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
  touchAuth();
  const resp = await fetch(`${API_BASE}/admin/runtime-mode`, {
    headers: { ...authHeaders() },
  });
  if (!resp.ok) throw new Error(`fetchRuntimeMode failed: ${resp.status}`);
  return resp.json();
}

export async function setRuntimeMode(mode: RuntimeMode): Promise<RuntimeModeInfo> {
  touchAuth();
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
  // R10.5.25 (深度审计 §5): 后端 register/login/revoke 返 key_rotated 字段,
  // true 表示"已有用户 key 轮换" (旧 key 立即失效), false 表示"新用户首次".
  // AuthDialog 据此显示 "欢迎回来 + 你的 key 已自动轮换" 提示.
  key_rotated?: boolean;
}

export interface UserInfo {
  user_id: string;
  display_name: string;
  created_at: number;
  open_mode: boolean;
}

// R10.5.55: register / login / revoke 三个独立函数. 替代旧的 registerOrLogin
// (旧版永远打 /auth/login 拿 key, 不区分新用户和老用户, 也无 revoke 端点).

export class AuthError extends Error {
  status: number;
  code: 'email_not_registered' | 'wrong_password' | 'already_registered' | 'weak_password' | 'invalid_email' | 'open_mode' | 'unknown';
  constructor(message: string, status: number, code: AuthError['code'] = 'unknown') {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function _mapAuthError(status: number, detail: string, mode: 'register' | 'login'): AuthError {
  const lower = detail.toLowerCase();
  if (lower.includes('已注册') || lower.includes('已存在')) {
    return new AuthError(detail, status, 'already_registered');
  }
  if (lower.includes('未注册')) {
    return new AuthError(detail, 404, 'email_not_registered');
  }
  if (lower.includes('密码错误')) {
    return new AuthError(detail, 401, 'wrong_password');
  }
  if (lower.includes('密码至少')) {
    return new AuthError(detail, 400, 'weak_password');
  }
  if (lower.includes('email 格式') || lower.includes('@')) {
    return new AuthError(detail, 400, 'invalid_email');
  }
  if (lower.includes('open_mode')) {
    return new AuthError(detail, 400, 'open_mode');
  }
  return new AuthError(detail, status);
}

export async function register(
  email: string,
  password: string = '',
  displayName: string = ''
): Promise<AuthResponse> {
  const resp = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  if (!resp.ok) {
    let detail = '注册失败';
    try { detail = (await resp.json()).detail || detail; } catch {}
    throw _mapAuthError(resp.status, detail, 'register');
  }
  const data: AuthResponse = await resp.json();
  setApiKey(data.api_key);
  return data;
}

export async function login(
  email: string,
  password: string = '',
  displayName: string = ''
): Promise<AuthResponse> {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  if (!resp.ok) {
    let detail = '登录失败';
    try { detail = (await resp.json()).detail || detail; } catch {}
    throw _mapAuthError(resp.status, detail, 'login');
  }
  const data: AuthResponse = await resp.json();
  setApiKey(data.api_key);
  return data;
}

// R10.5.55: 用户自助轮换 API key (登录后才有意义)
export async function revokeKey(): Promise<AuthResponse> {
  const key = getApiKey();
  if (!key) throw new AuthError('Not signed in', 401, 'unknown');
  const resp = await fetch(`${API_BASE}/auth/revoke`, {
    method: 'POST',
    headers: { 'X-API-Key': key, 'Content-Type': 'application/json' },
  });
  if (!resp.ok) {
    let detail = '轮换 key 失败';
    try { detail = (await resp.json()).detail || detail; } catch {}
    throw new AuthError(detail, resp.status);
  }
  const data: AuthResponse = await resp.json();
  setApiKey(data.api_key);  // 更新 sessionStorage
  return data;
}

// R10.5.55: logout 改成 async, 先调 /auth/logout 让服务端删 session, 再清本地.
// 旧实现只 setApiKey(null), 服务端 session 行泄漏.
export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    });
  } catch {
    // 服务端不可达时仍清本地, 用户体感一致
  }
  setApiKey(null);
}

// 保留旧 registerOrLogin 作为 fallback (向后兼容 Phase A 之前的代码路径)
export async function registerOrLogin(
  email: string,
  displayName: string = ''
): Promise<AuthResponse> {
  // 先试 register, 已注册则 fallback 到 login
  try {
    return await register(email, '', displayName);
  } catch (e: any) {
    if (e?.code === 'already_registered') {
      return await login(email, '', displayName);
    }
    throw e;
  }
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

// R10.5.32 (F7): CommandPalette /summarize + /critique 端点 helper.
// 后端 /api/v1/agents/{summarize,critique} 收 AgentPaperRequest, 返
// AgentPaperResponse. error 兜底返 {error: msg}, 让前端 handleCommand
// 一处集中处理成功/失败.
export interface AgentPaperRequest {
  paper_id: string;
  title: string;
  abstract?: string;
  query?: string;
}

export interface AgentPaperResponse {
  paper_id: string;
  agent: 'summarize' | 'critique';
  result: Record<string, unknown>;
  total_cost_usd: number;
  total_tokens_used: number;
  elapsed_seconds: number;
  runtime_mode: string;
}

export async function callAgent(
  agent: 'summarize' | 'critique',
  req: AgentPaperRequest
): Promise<AgentPaperResponse> {
  touchAuth();
  const resp = await fetch(`${API_BASE}/agents/${agent}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    let detail = `Agent ${agent} failed`;
    try {
      const err = await resp.json();
      detail = err.detail || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return resp.json();
}
