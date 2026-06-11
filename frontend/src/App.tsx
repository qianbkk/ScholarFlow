import { useCallback, useEffect, useState } from 'react';
import { CostDashboard } from './components/CostDashboard';
import { QueryPanel } from './components/QueryPanel';
import { ReportPanel } from './components/ReportPanel';
import { GraphPanel } from './components/GraphPanel';
import { ThemeSwitcher, type ThemeId } from './components/ThemeSwitcher';
import { LoginDialog } from './components/LoginDialog';
import { UserBadge } from './components/UserBadge';
import { useSearch } from './hooks/useSearch';
import {
  healthCheck,
  fetchMe,
  logout as authLogout,
  type UserInfo,
} from './services/api';

// Round 6 SIMPLIFY (REDUNDANT-004): 修复 onRetry 闭包丢失用户表单状态 bug
// 之前 onRetry={(q) => search(q)} 只传 query, useSearch.search 内部对
// budget/maxIter/provider 走 useState 默认值 (2.0/3/undefined),
// 用户上次改的预算/迭代/provider 全部丢失, 重试得到不一致的行为.
// 修复: 在 App.tsx 用 lastSearchOpts 记住上一次用户实际提交的参数,
// onRetry 用同一组参数复现上次搜索.

interface LastSearchOpts {
  budget: number;
  maxIter: number;
  provider?: string;
}

const THEME_STORAGE_KEY = 'sf-theme';
const VALID_THEMES: ThemeId[] = ['parchment', 'kraft', 'midnight', 'sage'];

function loadStoredTheme(): ThemeId {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored && (VALID_THEMES as string[]).includes(stored)) {
      return stored as ThemeId;
    }
    // R10.5.4 升级: 旧版本号用户 localStorage 存的是 light/warm/dark/eye,
    // 一次性迁移到新 ID. 缺失任意 ID 都回退到 parchment.
    const legacyMap: Record<string, ThemeId> = {
      light: 'parchment',
      warm: 'kraft',
      dark: 'midnight',
      eye: 'sage',
    };
    if (stored && legacyMap[stored]) {
      return legacyMap[stored];
    }
  } catch {
    // localStorage 可能在隐私模式不可用 — 静默回退默认
  }
  return 'parchment';
}

export default function App() {
  const {
    loading, error, result, lastQuery, search, reset,
    currentStep, elapsedSec, pipelineSteps,
  } = useSearch();
  const [serverOk, setServerOk] = useState<boolean | null>(null);
  const [elapsed, setElapsed] = useState(0);
  // Round 6 SIMPLIFY (REDUNDANT-004): 跟踪上一次成功提交的搜索参数, 给 onRetry 用
  const [lastSearchOpts, setLastSearchOpts] = useState<LastSearchOpts | null>(null);
  // R10 (M-17): 背景色主题状态 — localStorage 记忆, 4 套全部 WCAG AA (>4.5:1)
  const [theme, setTheme] = useState<ThemeId>(loadStoredTheme);
  // R10.5.3: 认证状态机 — 'loading' (启动检测中) | 'unauthenticated' (弹登录框)
  // | 'authenticated' (显示主界面).  配 UserInfo (含 open_mode) 控制 UserBadge.
  const [authState, setAuthState] = useState<'loading' | 'unauthenticated' | 'authenticated'>('loading');
  const [currentUser, setCurrentUser] = useState<UserInfo | null>(null);
  // OPEN_MODE=true 时允许用户主动关闭登录框 (实际不会触发, 走 authenticated).

  useEffect(() => {
    healthCheck()
      .then((d) => setServerOk(d.status === 'ok'))
      .catch(() => setServerOk(false));
  }, []);

  // R10.5.3: 启动时调 /auth/me 检测登录态.
  // - 200 → 拿到 UserInfo (含 open_mode), 进 authenticated
  // - 401 或无 key → 进 unauthenticated (弹 LoginDialog)
  // - 网络错 → 也按 unauthenticated 处理 (LoginDialog 内有错误提示, 不再白屏)
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

  const handleLoginSuccess = useCallback(async () => {
    // 重新拉一次 /auth/me 拿完整 UserInfo (含 created_at, open_mode 等)
    const u = await fetchMe();
    setCurrentUser(u);
    setAuthState(u ? 'authenticated' : 'unauthenticated');
  }, []);

  const handleLogout = useCallback(() => {
    authLogout();  // 清 localStorage
    setCurrentUser(null);
    setAuthState('unauthenticated');
  }, []);

  // 当 result 更新时，把后端返回的 elapsed 同步进来
  useEffect(() => {
    if (result?.elapsed_seconds) setElapsed(result.elapsed_seconds);
  }, [result]);

  // R10 (M-17): 主题切换 → 写 localStorage + 同步到 <html> element (让 body 继承)
  const handleThemeChange = useCallback((next: ThemeId) => {
    setTheme(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // 静默失败 — 不影响 UI 切换
    }
  }, []);

  // R10.5.4 启动时把 theme 写到 <html> (data-theme 属性), 让全局生效
  useEffect(() => {
    const html = document.documentElement;
    // 先清掉所有 theme-* class (含旧 light/warm/dark/eye 残留), 再加新的
    ['parchment', 'kraft', 'midnight', 'sage', 'light', 'warm', 'dark', 'eye'].forEach(
      (t) => html.classList.remove(`theme-${t}`)
    );
    html.classList.add(`theme-${theme}`);
    // 顺便在 console 打印一次对比度 (开发期验证)
    if (import.meta.env.DEV) {
      const contrasts: Record<ThemeId, string> = {
        parchment: '14.8:1',
        kraft: '11.2:1',
        midnight: '15.1:1',
        sage: '9.4:1',
      };
      console.info(`[theme] switched to ${theme} (contrast ${contrasts[theme]})`);
    }
  }, [theme]);

  // Round 6 SIMPLIFY (REDUNDANT-004): 包装 search, 在调用前先记住当前表单参数.
  // 这样 onRetry 闭包能拿到和用户上次提交完全一致的 budget/maxIter/provider.
  // search 签名本身不变 (useSearch.search(q, budget=2.0, maxIter=3, provider?) ),
  // 这里只是把"用户实际选择的值"存到 lastSearchOpts, 不修改下游.
  const handleSearch = useCallback(
    (q: string, budget: number, maxIter: number, provider?: string) => {
      setLastSearchOpts({ budget, maxIter, provider });
      search(q, budget, maxIter, provider);
    },
    [search]
  );

  return (
    // R10.5.4 Editorial Knowledge: 整体保持 4 套主题 CSS 变量驱动的 bg/text/border.
    <div
      className="h-screen flex flex-col font-ui"
      style={{ backgroundColor: 'var(--sf-bg)', color: 'var(--sf-text)' }}
    >
      {/* === 报头 (Editorial Masthead) ===
          R10.5.4 重设计: 报头三段式 — 刊名 (Fraunces italic) + 副刊号 (IBM Plex mono 小字) + 右侧主题/用户.
          顶部加双线 (经典期刊装订线) 替代单 border, 强化"翻杂志"的视觉感. */}
      <header className="sf-rise">
        <div
          className="px-4 sm:px-6 py-3 flex items-end justify-between gap-4 border-b-2"
          style={{ borderColor: 'var(--sf-text)' }}
        >
          <div className="flex items-baseline gap-3 min-w-0">
            <h1
              className="font-display text-2xl sm:text-3xl font-semibold italic tracking-tight"
              style={{ color: 'var(--sf-text)' }}
            >
              Scholar<span style={{ color: 'var(--sf-accent)' }}>Flow</span>
            </h1>
            <span
              className="font-mono text-[10px] uppercase tracking-[0.18em] hidden sm:inline opacity-60"
            >
              Vol. 1 · 科研文献智能检索
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <UserBadge
              user={currentUser}
              openMode={currentUser?.open_mode ?? true}
              onLogout={handleLogout}
              loading={authState === 'loading'}
            />
            <ThemeSwitcher current={theme} onChange={handleThemeChange} />
          </div>
        </div>
        {/* 报头底部细线 (印刷"切线") */}
        <div className="h-px" style={{ backgroundColor: 'var(--sf-border)' }} />
      </header>

      <div className="sf-rise sf-rise-d1">
        <CostDashboard result={result} loading={loading} elapsed={elapsed} />
      </div>

      {serverOk === false && (
        <div
          className="mx-4 sm:mx-6 mt-3 px-4 py-2.5 text-xs flex items-center gap-2 font-ui"
          style={{
            backgroundColor: 'var(--sf-bg-elev)',
            color: 'var(--sf-accent)',
            borderLeft: '3px solid var(--sf-accent)',
          }}
        >
          <span className="font-mono text-base">⚠</span>
          <span>
            <span className="font-semibold">后端未连通</span> · http://127.0.0.1:8000 ·
            请先运行 <code className="font-mono px-1.5 py-0.5 bg-[var(--sf-bg)] border border-[var(--sf-border)]">
              uvicorn backend.main:app
            </code>
          </span>
        </div>
      )}

      {error && (
        <div
          className="mx-4 sm:mx-6 mt-3 px-4 py-2.5 text-xs flex items-center gap-2"
          style={{
            backgroundColor: 'var(--sf-bg-elev)',
            color: 'var(--sf-accent)',
            borderLeft: '3px solid var(--sf-accent)',
          }}
        >
          <span className="font-mono">[!]</span>
          <span className="font-ui">{error}</span>
        </div>
      )}

      {/* Round 6 S5: 移动端响应式 — lg 以下三栏折叠为单栏纵排.
          之前 flex 横排在 768px 以下挤, ReportPanel/GraphPanel 几乎不可见.
          现在 flex-col 默认 + overflow-y-auto 让整个页面竖向滚动 (避免嵌套 scroll);
          lg+ 切回 flex-row + overflow-hidden 让三栏独立内部滚动.
          min-h-0 允许 flex 子项收缩到 0 (flex 默认 min-height: auto 会撑破父容器).
          R10.5.4: 加 sf-rise-d2/d3 让中间栏 + 右侧栏按顺序淡入, 报头已 d0. */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-y-auto lg:overflow-hidden">
        <div className="sf-rise sf-rise-d1 min-h-0 flex flex-col lg:flex-row w-full lg:contents">
          <QueryPanel
            loading={loading}
            onSearch={handleSearch}
            onReset={reset}
            papers={result?.ranked_papers ?? []}
            lastQuery={lastQuery}
            currentStep={currentStep}
            elapsedSec={elapsedSec}
            pipelineSteps={pipelineSteps}
            isDegradedResponse={result?.is_degraded_response ?? false}
            fallbackPaperCount={result?.fallback_paper_count ?? 0}
          />
          {/* Round 6 M1: App.tsx 接 errorMsg + onRetry 到 ReportPanel,
              激活 R4 U4 死代码 (用户重试按钮生效).
              Round 6 SIMPLIFY (REDUNDANT-004): onRetry 改用 lastSearchOpts 复现
              用户上次表单状态 (预算/迭代/provider), 修复闭包丢失 bug. */}
          <ReportPanel
            report={result?.report ?? ''}
            loading={loading}
            query={lastQuery}
            errorMsg={error}
            lastQuery={lastQuery}
            bibtex={result?.bibtex ?? ''}
            ris={result?.ris ?? ''}
            onRetry={(q) =>
              lastSearchOpts
                ? search(q, lastSearchOpts.budget, lastSearchOpts.maxIter, lastSearchOpts.provider)
                : search(q)
            }
          />
          <GraphPanel graph={result?.citation_graph ?? null} />
        </div>
      </div>

      {/* R10.5.3: 认证对话框 — 未登录时强制弹出 (OPEN_MODE=false).
          z-50 模态, 阻断所有下层交互, 防止用户绕过认证直接触发 search. */}
      {authState === 'unauthenticated' && (
        <LoginDialog
          requireAuth
          onSuccess={handleLoginSuccess}
        />
      )}
    </div>
  );
}
