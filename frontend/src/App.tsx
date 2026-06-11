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
    recentSearches, clearRecentSearches,
    budgetExceeded, dismissBudgetExceeded,
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
  // R10.5.5: 跨组件论文聚焦 — 论文列表 / 图谱节点 / 报告引用表 三者互相同步高亮
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  // R10.5.5: 快捷键面板显示状态
  const [showShortcuts, setShowShortcuts] = useState<boolean>(false);

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
      setSelectedPaperId(null);  // 新搜索清掉旧高亮
      search(q, budget, maxIter, provider);
    },
    [search]
  );

  // R10.5.5: 跨组件论文聚焦回调
  // QueryPanel / ReportPanel / GraphPanel 都会调它, 状态集中在这里, 三个面板共享
  const handleSelectPaper = useCallback((paperId: string | null) => {
    setSelectedPaperId(paperId);
  }, []);

  // R10.5.5: 成本超限恢复 — 1.5x 预算重跑
  // 旧版用户必须改表单 → 点搜索. 新版显示"调高预算"按钮一键重跑, 预算 = max(原预算 * 1.5, 已花 * 1.2)
  // 保证再次跑能 cover 已有支出 + 一些缓冲.
  const handleBumpBudget = useCallback(() => {
    if (!budgetExceeded || !lastQuery || !lastSearchOpts) return;
    const newBudget = Math.max(
      budgetExceeded.budget_usd * 1.5,
      budgetExceeded.cost_usd * 1.2,
      budgetExceeded.budget_usd + 0.5
    );
    const rounded = Math.round(newBudget * 100) / 100;  // 保留 2 位
    setLastSearchOpts({ ...lastSearchOpts, budget: rounded });
    setSelectedPaperId(null);
    search(lastQuery, rounded, lastSearchOpts.maxIter, lastSearchOpts.provider);
    dismissBudgetExceeded();
  }, [budgetExceeded, lastQuery, lastSearchOpts, search, dismissBudgetExceeded]);

  // R10.5.5: 全局键盘快捷键
  // Cmd/Ctrl+K 或 / → 聚焦 query 输入框
  // Esc → 取消当前搜索 (loading 时) 或关闭快捷键面板
  // ? (shift+/) → 显示快捷键面板
  // 输入框聚焦时禁用, 避免抢用户输入.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 在输入框/textarea 中不抢快捷键 (用户正常输入 /)
      const target = e.target as HTMLElement | null;
      const isInput =
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable);

      if (showShortcuts && e.key === 'Escape') {
        e.preventDefault();
        setShowShortcuts(false);
        return;
      }

      if (e.key === 'Escape' && loading) {
        e.preventDefault();
        reset();
        return;
      }

      if (isInput) return;

      // Cmd/Ctrl+K → 聚焦 query
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        document.querySelector<HTMLTextAreaElement>('[data-search-input]')?.focus();
        return;
      }
      // / → 聚焦 query (GitHub / Slack 风格)
      if (e.key === '/') {
        e.preventDefault();
        document.querySelector<HTMLTextAreaElement>('[data-search-input]')?.focus();
        return;
      }
      // ? → 快捷键面板
      if (e.key === '?') {
        e.preventDefault();
        setShowShortcuts((s) => !s);
        return;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [loading, reset, showShortcuts]);

  return (
    // R10.5.4 Editorial Knowledge: 整体保持 4 套主题 CSS 变量驱动的 bg/text/border.
    <div
      className="h-screen flex flex-col font-ui"
      style={{ backgroundColor: 'var(--sf-bg)', color: 'var(--sf-text)' }}
    >
      {/* === 报头 (Editorial Masthead) ===
          R10.5.4 重设计: 报头三段式 — 刊名 (Fraunces italic) + 副刊号 (IBM Plex mono 小字) + 右侧主题/用户.
          顶部加双线 (经典期刊装订线) 替代单 border, 强化"翻杂志"的视觉感.
          R10.5.6 Fix: header 加 z-30, 否则 ThemeSwitcher / UserBadge 的 z-20 下拉
          会被后续 CostDashboard 兄弟节点 (默认 z-auto, 后渲染赢) 盖住, 表现为
          "点不到主题切换" / "点到了引文图谱". */}
      <header className="sf-rise relative z-30">
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
          <div className="flex items-center gap-2 shrink-0 relative">
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
          className="mx-4 sm:mx-6 mt-3 px-4 py-2.5 text-xs flex items-center gap-2 flex-wrap"
          style={{
            backgroundColor: 'var(--sf-bg-elev)',
            color: 'var(--sf-accent)',
            borderLeft: '3px solid var(--sf-accent)',
          }}
        >
          <span className="font-mono">[!]</span>
          <span className="font-ui flex-1 min-w-0">{error}</span>
          {/* R10.5.5: 成本超限时, error 旁显示"调高预算"按钮一键重跑 */}
          {budgetExceeded && (
            <button
              type="button"
              onClick={handleBumpBudget}
              className="font-mono text-[10px] uppercase tracking-[0.12em] px-2.5 py-1 transition-colors"
              style={{
                backgroundColor: 'var(--sf-accent)',
                color: 'var(--sf-bg)',
              }}
              data-testid="bump-budget-btn"
            >
              调高到 ${(
                Math.max(
                  budgetExceeded.budget_usd * 1.5,
                  budgetExceeded.cost_usd * 1.2,
                  budgetExceeded.budget_usd + 0.5
                )
              ).toFixed(2)} 重试 →
            </button>
          )}
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
            // R10.5.5: 跨组件论文聚焦
            selectedPaperId={selectedPaperId}
            onSelectPaper={handleSelectPaper}
            // R10.5.5: 最近搜索
            recentSearches={recentSearches}
            onClearRecent={clearRecentSearches}
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
            // R10.5.5: 报告内引用表 → 跨组件论文聚焦
            selectedPaperId={selectedPaperId}
            onSelectPaper={handleSelectPaper}
            papers={result?.ranked_papers ?? []}
          />
          <GraphPanel
            graph={result?.citation_graph ?? null}
            // R10.5.5: 图谱节点 → 跨组件论文聚焦
            selectedPaperId={selectedPaperId}
            onSelectPaper={handleSelectPaper}
          />
        </div>
      </div>

      {/* R10.5.5: 快捷键面板 (按 ? 触发) */}
      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />}

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

// R10.5.5: 快捷键说明浮层 — 期刊"版权页" 风格
const SHORTCUTS: Array<{ keys: string[]; label: string; desc: string }> = [
  { keys: ['⌘', 'K'],     label: '聚焦查询',     desc: '快速跳到研究问题输入框' },
  { keys: ['/'],           label: '聚焦查询',     desc: '同上 (GitHub / Slack 风格)' },
  { keys: ['Esc'],         label: '取消 / 关闭',  desc: '中断正在跑的检索流水线, 或关闭本面板' },
  { keys: ['?'],           label: '快捷键',       desc: '显示本面板 (再次按 ? 关闭)' },
];

function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sf-fade"
      onClick={onClose}
      style={{ backgroundColor: 'rgba(13, 13, 13, 0.55)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcuts-title"
    >
      <div
        className="relative w-full max-w-md p-7 sf-rise font-ui"
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: 'var(--sf-bg)',
          color: 'var(--sf-text)',
          border: '1px solid var(--sf-border)',
          boxShadow: '0 16px 48px rgba(0,0,0,0.10)',
        }}
      >
        <div
          className="absolute top-0 left-0 right-0 h-1"
          style={{ backgroundColor: 'var(--sf-accent)' }}
        />
        <div className="flex items-start justify-between mb-5">
          <div>
            <div
              className="font-mono text-[9px] uppercase tracking-[0.25em] mb-1"
              style={{ color: 'var(--sf-accent)' }}
            >
              § Colophon · 版权页
            </div>
            <h2
              id="shortcuts-title"
              className="font-display italic font-semibold text-2xl leading-tight"
            >
              快捷键
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="font-display italic text-2xl leading-none px-1"
            style={{ color: 'var(--sf-muted)' }}
          >
            ×
          </button>
        </div>
        <div className="space-y-2.5">
          {SHORTCUTS.map((s, i) => (
            <div
              key={i}
              className="flex items-center gap-4 py-2 border-b"
              style={{ borderColor: 'var(--sf-border)' }}
            >
              <div className="flex items-center gap-1 shrink-0 w-24">
                {s.keys.map((k, ki) => (
                  <kbd
                    key={ki}
                    className="font-mono text-[10px] font-semibold px-1.5 py-0.5 min-w-[20px] text-center"
                    style={{
                      backgroundColor: 'var(--sf-bg-elev)',
                      color: 'var(--sf-text)',
                      border: '1px solid var(--sf-border)',
                      borderBottomWidth: '2px',
                    }}
                  >
                    {k}
                  </kbd>
                ))}
              </div>
              <div className="flex-1 min-w-0">
                <div
                  className="font-display italic font-semibold text-[14px]"
                  style={{ color: 'var(--sf-text)' }}
                >
                  {s.label}
                </div>
                <div
                  className="text-[11px] font-body mt-0.5"
                  style={{ color: 'var(--sf-muted)' }}
                >
                  {s.desc}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div
          className="mt-5 pt-3 text-[10px] font-mono uppercase tracking-[0.18em] text-center"
          style={{ color: 'var(--sf-muted)' }}
        >
          ❦ &nbsp; 按 ? 或 Esc 关闭 &nbsp; ❦
        </div>
      </div>
    </div>
  );
}
