import { useCallback, useEffect, useState } from 'react';
import { CostDashboard } from './components/CostDashboard';
import { QueryPanel } from './components/QueryPanel';
import { ReportPanel } from './components/ReportPanel';
import { GraphPanel } from './components/GraphPanel';
import { ThemeSwitcher, type ThemeId } from './components/ThemeSwitcher';
import { useSearch } from './hooks/useSearch';
import { healthCheck } from './services/api';

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
const VALID_THEMES: ThemeId[] = ['light', 'warm', 'dark', 'eye'];

function loadStoredTheme(): ThemeId {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored && (VALID_THEMES as string[]).includes(stored)) {
      return stored as ThemeId;
    }
  } catch {
    // localStorage 可能在隐私模式不可用 — 静默回退默认
  }
  return 'light';
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

  useEffect(() => {
    healthCheck()
      .then((d) => setServerOk(d.status === 'ok'))
      .catch(() => setServerOk(false));
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

  // R10 (M-17): 启动时把 theme 写到 <html> (data-theme 属性), 让全局生效
  useEffect(() => {
    const html = document.documentElement;
    // 先清掉旧 theme class, 再加新的 (避免 stacking)
    VALID_THEMES.forEach((t) => html.classList.remove(`theme-${t}`));
    html.classList.add(`theme-${theme}`);
    // 顺便在 console 打印一次对比度 (开发期验证)
    if (import.meta.env.DEV) {
      const contrasts: Record<ThemeId, string> = {
        light: '16.5:1',
        warm: '13.2:1',
        dark: '14.5:1',
        eye: '6.8:1',
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
    // R10 (M-17): bg-theme-light 是默认浅色, text-theme-light 是高对比文字 (#0f172a)
    // 全部 4 套主题都通过 tailwind.config.js 扩展的颜色对, 对比度 > 4.5:1 (WCAG AA)
    <div
      className="h-screen flex flex-col"
      style={{ backgroundColor: 'var(--sf-bg)', color: 'var(--sf-text)' }}
    >
      {/* R10 (M-17): 顶部 toolbar — 右侧放 ThemeSwitcher, 切换不刷新页面 */}
      <div
        className="flex items-center justify-between px-4 py-1.5 border-b"
        style={{ borderColor: 'var(--sf-border, #e2e8f0)' }}
      >
        <div className="flex items-center gap-2 text-xs opacity-70">
          <span>ScholarFlow</span>
        </div>
        <ThemeSwitcher current={theme} onChange={handleThemeChange} />
      </div>

      <CostDashboard result={result} loading={loading} elapsed={elapsed} />

      {serverOk === false && (
        <div className="bg-rose-50 border-b border-rose-200 px-4 py-2 text-xs text-rose-700 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-rose-500" />
          后端服务未连通 (http://127.0.0.1:8000)。请先运行
          <code className="bg-rose-100 px-1.5 py-0.5 rounded font-mono">
            uvicorn backend.main:app
          </code>
        </div>
      )}

      {error && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-xs text-amber-700 flex items-center gap-2">
          <span>[!]</span> {error}
        </div>
      )}

      {/* Round 6 S5: 移动端响应式 — lg 以下三栏折叠为单栏纵排.
          之前 flex 横排在 768px 以下挤, ReportPanel/GraphPanel 几乎不可见.
          现在 flex-col 默认 + overflow-y-auto 让整个页面竖向滚动 (避免嵌套 scroll);
          lg+ 切回 flex-row + overflow-hidden 让三栏独立内部滚动.
          min-h-0 允许 flex 子项收缩到 0 (flex 默认 min-height: auto 会撑破父容器). */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-y-auto lg:overflow-hidden">
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
  );
}
