/**
 * R10.5.31 (F4): 4 个 Context 之一 — AppContext
 *
 * 装: 认证 (authState + currentUser) + 主题 (theme) + 健康 (serverOk)
 *     + 运行时模式 (runtimeMode).
 * 之前散在 App.tsx 4 个 useState, 4 个 useEffect 拉数据, 1 个 useCallback
 * 处理主题. 现在集中到 1 个 provider, 子组件 import { useApp } 即用.
 *
 * Why split this way (不是按"组件"分而是按"域"分):
 *   - AppContext = 跨面板不变量, 跟搜索结果无关, 几乎不变
 *   - SearchContext (useSearch) = 流水线状态, 高频变
 *   - SelectionContext = 论文/图谱选中, 中频变
 *   - UIContext = 模态/快捷键/命令面板开关, 跟 focus 强相关
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import {
  healthCheck,
  fetchMe,
  fetchRuntimeMode,
  setRuntimeMode as apiSetRuntimeMode,
  type UserInfo,
  type RuntimeMode,
} from '../services/api';
import type { ThemeId } from '../components/ThemeSwitcher';
// R10.5.51 cleanup (BACKLOG B-008): 改用 STORAGE_KEYS 中央化.
import { STORAGE_KEYS } from '../lib/storageKeys';

const THEME_STORAGE_KEY = STORAGE_KEYS.theme;
const VALID_THEMES: ThemeId[] = ['parchment', 'kraft', 'midnight', 'sage'];
const LEGACY_THEME_MAP: Record<string, ThemeId> = {
  light: 'parchment',
  warm: 'kraft',
  dark: 'midnight',
  eye: 'sage',
};

function loadStoredTheme(): ThemeId {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored && (VALID_THEMES as string[]).includes(stored)) {
      return stored as ThemeId;
    }
    if (stored && LEGACY_THEME_MAP[stored]) {
      return LEGACY_THEME_MAP[stored];
    }
  } catch {
    // 隐私模式 / SSR 兜底
  }
  return 'parchment';
}

export type AuthState = 'loading' | 'unauthenticated' | 'authenticated';

interface AppContextValue {
  // ===== 主题 =====
  theme: ThemeId;
  setTheme: (next: ThemeId) => void;
  // ===== 认证 =====
  authState: AuthState;
  currentUser: UserInfo | null;
  onLoginSuccess: (user: UserInfo) => void;
  onLogout: () => void;
  // ===== 后端连通 =====
  serverOk: boolean | null;
  // ===== Runtime mode (mock / real) =====
  runtimeMode: RuntimeMode | null;
  setRuntimeMode: (mode: RuntimeMode) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  // === theme ===
  const [theme, setThemeState] = useState<ThemeId>(loadStoredTheme);
  const setTheme = useCallback((next: ThemeId) => {
    setThemeState(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // 静默失败
    }
  }, []);

  // === 主题写到 <html> ===
  useEffect(() => {
    const html = document.documentElement;
    ['parchment', 'kraft', 'midnight', 'sage', 'light', 'warm', 'dark', 'eye'].forEach(
      (t) => html.classList.remove(`theme-${t}`)
    );
    html.classList.add(`theme-${theme}`);
  }, [theme]);

  // === auth ===
  const [authState, setAuthState] = useState<AuthState>('loading');
  const [currentUser, setCurrentUser] = useState<UserInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMe()
      .then((u) => {
        if (cancelled) return;
        if (u) {
          setCurrentUser(u);
          setAuthState('authenticated');
        } else {
          setCurrentUser(null);
          setAuthState('unauthenticated');
        }
      })
      .catch(() => {
        if (cancelled) return;
        setCurrentUser(null);
        setAuthState('unauthenticated');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onLoginSuccess = useCallback((user: UserInfo) => {
    setCurrentUser(user);
    setAuthState('authenticated');
  }, []);

  const onLogout = useCallback(() => {
    setCurrentUser(null);
    setAuthState('unauthenticated');
  }, []);

  // === serverOk ===
  const [serverOk, setServerOk] = useState<boolean | null>(null);
  useEffect(() => {
    healthCheck()
      .then((d) => setServerOk(d.status === 'ok'))
      .catch(() => setServerOk(false));
  }, []);

  // === runtime mode ===
  const [runtimeMode, setRuntimeModeState] = useState<RuntimeMode | null>(null);
  useEffect(() => {
    fetchRuntimeMode()
      .then((info) => setRuntimeModeState(info.mode))
      .catch(() => setRuntimeModeState('real'));
  }, []);

  const setRuntimeMode = useCallback((mode: RuntimeMode) => {
    setRuntimeModeState(mode);  // 乐观
    apiSetRuntimeMode(mode)
      .then((info) => setRuntimeModeState(info.mode))
      .catch(() => {
        // 失败回滚
        setRuntimeModeState((prev) => prev);
        console.warn('setRuntimeMode failed, rolled back');
      });
  }, []);

  return (
    <AppContext.Provider
      value={{
        theme, setTheme,
        authState, currentUser, onLoginSuccess, onLogout,
        serverOk,
        runtimeMode, setRuntimeMode,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error('useApp must be used within <AppProvider>');
  }
  return ctx;
}
