import { useCallback, useEffect, useMemo, useState } from 'react';
import { CostDashboard } from './components/CostDashboard';
import { QueryPanel } from './components/QueryPanel';
import { STORAGE_KEYS } from './lib/storageKeys';
import { ReportPanel } from './components/ReportPanel';
import { GraphPanel } from './components/GraphPanel';
import { ThemeSwitcher, type ThemeId } from './components/ThemeSwitcher';
import { ThemeToggle } from './components/ThemeToggle';
import { LayoutToggle, useLayoutMode } from './components/LayoutToggle';
import { LoginDialog } from './components/LoginDialog';
import { UserBadge } from './components/UserBadge';
import { CockpitDashboard } from './components/CockpitDashboard';
import { EvolutionSlider } from './components/EvolutionSlider';
import { CompareDrawer } from './components/CompareDrawer';
import { CommandPalette } from './components/CommandPalette';
import { ChangelogModal } from './components/ChangelogModal';
// R10.5.31 (F4): 4 个 Context 按域拆分, 删 13 个 useState.
import { AppProvider, useApp } from './contexts/AppContext';
import { SelectionProvider, useSelection } from './contexts/SelectionContext';
import { UIProvider, useUI } from './contexts/UIContext';
import { useSearch } from './hooks/useSearch';
import {
  healthCheck,
  logout as authLogout,
  callAgent,
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

// R10.5.31 (F4): theme 加载逻辑搬到 AppContext, App.tsx 不再需要
// THEME_STORAGE_KEY + VALID_THEMES. 真值在 AppContext.tsx (useApp hook).
// R10.5.51 cleanup: THEME_STORAGE_KEY 也走 STORAGE_KEYS 中央化
// (AppContext.tsx 已用). 详见 BACKLOG.md D 节 (R10.5.51 cleanup 整体记录).
export default function App() {
  // R10.5.31 (F4): 外层只做 Provider 包装, 业务逻辑挪到 AppInner.
  // 这样 4 个 Context 的副作用 (fetchMe / healthCheck / fetchRuntimeMode) 在
  // Provider mount 时跑一次, 不会跟业务组件混在一起.
  return (
    <AppProvider>
      <SelectionProvider>
        <UIProvider>
          <AppInner />
        </UIProvider>
      </SelectionProvider>
    </AppProvider>
  );
}

function AppInner() {
  const {
    loading, error, result, lastQuery, search, reset,
    currentStep, elapsedSec, pipelineSteps,
    recentSearches, clearRecentSearches,
    budgetExceeded, dismissBudgetExceeded,
    events, graphSnapshots,
  } = useSearch();

  // R10.5.40 (Agent 1): 布局模式 — 3-col vs 焦点单栏.
  // focus 模式隐藏 GraphPanel (App.tsx 不渲染它即可, 不影响 GraphPanel 内部状态).
  // QueryPanel + ReportPanel 始终显示 (任务硬约束).
  const [layoutMode] = useLayoutMode();
  const showGraph = layoutMode === 'three-col';

  // R10.5.31 (F4): 13 个 useState → 4 个 Context. 只剩 2 个真正属于
  // search 业务域的 state 留本地: elapsed (跟 result 同步) + lastSearchOpts
  // (Round 6 SIMPLIFY REDUNDANT-004 修的闭包 bug, 必须留).
  const [elapsed, setElapsed] = useState(0);
  const [lastSearchOpts, setLastSearchOpts] = useState<LastSearchOpts | null>(null);

  // ===== Contexts (替代散 useState) =====
  const {
    theme, setTheme,
    authState, currentUser, onLoginSuccess: handleLoginSuccess, onLogout: handleLogout,
    serverOk, runtimeMode, setRuntimeMode: handleChangeRuntimeMode,
  } = useApp();
  const {
    state: selState,
    focusPaper: setSelectedPaperId,
    togglePaperSelection,
    clearPaperSelection,
    expandNode: setExpandedNodeId,
    setFilters, patchFilters, resetFilters,
  } = useSelection();
  const {
    changelogOpen, openChangelog, closeChangelog,
    shortcutsOpen, toggleShortcuts,
    cmdPaletteOpen, openCmdPalette, closeCmdPalette,
  } = useUI();

  // 把 4 个 useState 抽到 Context 后, 别名保持兼容让下面 JSX 不大改.
  const selectedPaperId = selState.focusedPaperId;
  const selectedPaperIds = selState.selectedPaperIds;
  const expandedNodeId = selState.expandedNodeId;
  const filters = selState.filters;
  const changelogOpen2 = changelogOpen;  // 别名避免 shadow
  const showShortcuts = shortcutsOpen;

  // handleThemeChange 别名: App.tsx 内用 setTheme 即可
  const handleThemeChange = setTheme;

  // 当 result 更新时，把后端返回的 elapsed 同步进来
  useEffect(() => {
    if (result?.elapsed_seconds) setElapsed(result.elapsed_seconds);
  }, [result]);

  // Cmd+K 全局快捷键 — 提到顶层 (避免 useCommandPalette hook 重复注册)
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      const mod = isMac ? e.metaKey : e.ctrlKey;
      if (mod && e.key === 'k') {
        e.preventDefault();
        if (cmdPaletteOpen) closeCmdPalette();
        else openCmdPalette();
      }
      if (e.key === '?' && !cmdPaletteOpen) {
        toggleShortcuts();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [cmdPaletteOpen, openCmdPalette, closeCmdPalette, toggleShortcuts]);

  // R10.5.31 (F5): CommandPalette 13 个命令接真 handler. 11 个接真,
  // 2 个 (/summarize + /critique) 保留 console.info 因为后端没对应 endpoint
  // (需要新建 /api/v1/agents/summarize + /api/v1/agents/critique, 留 F7+).
  // 接真原则: 命令在 CommandPalette 内部只负责元数据 + onExecuteCommand
  // 委托, 实际副作用都在 App.tsx 这一处集中, 方便维护. 放到 handleThemeChange
  // 之后避免 forward-reference 错误.
  const handleCommand = useCallback((cmdId: string) => {
    switch (cmdId) {
      // ===== view =====
      case 'compare':
        // R10.5.30 (D5 P1-2): CompareDrawer 实际是 selectedPaperIds.length===2
        // 时自动渲染, 没有独立 setCompareOpen. command 触发选最近 2 篇.
        // 这里只 console.info 提示, 实际触发靠 QueryPanel Shift+click 多选.
        console.info('[CommandPalette] /compare: 在论文列表 Shift+click 选 2 篇自动打开对比');
        break;
      case 'expand-graph':
        // GraphPanel 没暴露 imperative handle, 这里仅 console.info.
        console.info('[CommandPalette] /expand graph: 暂未接 (GraphPanel ref 待加)');
        break;
      // ===== export =====
      case 'export-bibtex':
      case 'export-ris':
      case 'export-csv': {
        // 触发浏览器下载 — 走 Blob + a[download] 标准 pattern.
        const fmt = cmdId.replace('export-', '') as 'bibtex' | 'ris' | 'csv';
        const ref = (result as unknown as Record<string, unknown> | null)?.[fmt];
        if (typeof ref === 'string' && ref.length > 0) {
          const blob = new Blob([ref], { type: 'text/plain;charset=utf-8' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `scholarflow-${fmt}.${fmt === 'csv' ? 'csv' : fmt}`;
          a.click();
          URL.revokeObjectURL(url);
        } else {
          console.info(`[CommandPalette] /export ${fmt}: 无可导出的内容 (result.${fmt} 缺失), 请先跑一次搜索`);
        }
        break;
      }
      // ===== filter =====
      case 'filter-rct':
        patchFilters({ methods: Array.from(new Set([...filters.methods, 'RCT'])) });
        break;
      case 'filter-recent':
        patchFilters({ yearRange: '3' });
        break;
      case 'filter-high-quality':
        patchFilters({ minQualityScore: 8 });
        break;
      case 'reset-filters':
        resetFilters();
        break;
      // ===== general =====
      case 'toggle-dark-mode': {
        // 4 套主题循环切 (parchment → kraft → midnight → sage → parchment).
        const order: ThemeId[] = ['parchment', 'kraft', 'midnight', 'sage'];
        const idx = order.indexOf(theme);
        const next = order[(idx + 1) % order.length] ?? 'parchment';
        handleThemeChange(next);
        break;
      }
      case 'focus-query':
        // 跟 QueryPanel 现有 [data-search-input] 约定一致.
        document.querySelector<HTMLTextAreaElement>('[data-search-input]')?.focus();
        break;
      // ===== agent (F7: 调真后端 /api/v1/agents/{summarize,critique}) =====
      case 'summarize':
      case 'critique': {
        // 取最近一篇 result 里的论文作为目标 (CommandPalette 当前不接 selectedPaperId).
        // 用户体验: 跑过 /search 后 CommandPalette /summarize 或 /critique
        // 直接作用于最近一篇. 后续可扩成"让用户选哪篇"二级菜单.
        const target = (result?.ranked_papers ?? [])[0] as
          | { paper_id?: string; title?: string; abstract?: string }
          | undefined;
        if (!target?.title) {
          console.info(`[CommandPalette] /${cmdId}: 请先跑一次搜索拿到论文再触发此命令`);
          break;
        }
        const agent = cmdId;  // 'summarize' | 'critique'
        callAgent(agent as 'summarize' | 'critique', {
          paper_id: target.paper_id || 'unknown',
          title: target.title,
          abstract: target.abstract || '',
          query: lastQuery,
        })
          .then((resp) => {
            // R10.5.32 (F7): 成功/失败都 console.info, 后续可挂到 UI (e.g. toast
            // 或 inline card). 当前先打 log 让用户看到 agent 真跑通.
            if ('error' in resp.result) {
              console.warn(`[CommandPalette] /${agent} 失败:`, resp.result.error);
            } else {
              console.info(
                `[CommandPalette] /${agent} 完成 (cost=$${resp.total_cost_usd.toFixed(4)}, ` +
                `tokens=${resp.total_tokens_used}, elapsed=${resp.elapsed_seconds}s, mode=${resp.runtime_mode}):`,
                resp.result
              );
            }
          })
          .catch((err) => {
            console.warn(`[CommandPalette] /${agent} 请求失败:`, err?.message || err);
          });
        break;
      }
      default:
        console.info('[CommandPalette] unknown command:', cmdId);
    }
  }, [result, theme, handleThemeChange]);

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
        toggleShortcuts();
        return;
      }

      if (e.key === 'Escape' && loading) {
        e.preventDefault();
        reset();
        return;
      }

      if (isInput) return;

      // Cmd/Ctrl+K → 命令面板 (优先) 或聚焦 query (兜底).
      // R10.5.29 (code-review): useCommandPalette hook 也注册了 Cmd+K, 两个监听器
      // 触发顺序由 useEffect 顺序决定, 旧实现可能 hook 先注册但 App.tsx handler
      // 先 return → 用户按 Cmd+K 只聚焦 query 不开面板. 修法: 命令面板 open 时
      // 让 hook 接管, 关闭时 App.tsx handler 兜底聚焦 query. 冲突解决靠状态查询
      // (cmdPalette.isOpen) 而非监听器顺序.
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        if (!cmdPaletteOpen) {
          openCmdPalette();
        } else {
          closeCmdPalette();
        }
        e.preventDefault();
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
        toggleShortcuts();
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
            {/* R10.5.40 (Agent 1): 二元暗黑模式开关 — 跟 4 套 Editorial 主题正交.
                ThemeSwitcher 选色系 (parchment/kraft/midnight/sage),
                ThemeToggle 开关"夜间模式" 把当前色系翻转到暗底. */}
            <ThemeToggle />
            {/* R10.5.40 (Agent 1): 3-col / 焦点单栏 布局切换. */}
            <LayoutToggle />
            <ThemeSwitcher current={theme} onChange={handleThemeChange} />
          </div>
        </div>
        {/* 报头底部细线 (印刷"切线") */}
        <div className="h-px" style={{ backgroundColor: 'var(--sf-border)' }} />
      </header>

      <div className="sf-rise sf-rise-d1">
        <CostDashboard result={result} loading={loading} elapsed={elapsed} />
      </div>

      {/* R10.5.28 (Holographic 集成): 8 节点态势感知驾驶舱. 跟 CostDashboard 同源数据
          (useSearch.events), 但 CockpitDashboard 是横向 8 舱室 + Thought Stream,
          比 CostDashboard 的 4 个标量更"驾驶舱"感. 仅在有 events 或在跑时显示. */}
      {(events.length > 0 || loading) && (
        <div className="mx-4 sm:mx-6 mt-2">
          <CockpitDashboard
            events={events}
            isRunning={loading}
            expandedNodeId={expandedNodeId}
            onExpandNode={setExpandedNodeId}
          />
        </div>
      )}

      {/* R10.5.28 (Holographic 集成): 演化时间轴. build_graph 节点每完成一次推
          一个图谱快照, EvolutionSlider 让用户拖时间轴看 V1 → V2 → V3 生长. */}
      {graphSnapshots.length > 0 && (
        <div className="mx-4 sm:mx-6 mt-2">
          <EvolutionSlider
            snapshots={graphSnapshots}
            currentIteration={graphSnapshots[graphSnapshots.length - 1].iteration}
            onIterationChange={() => {/* 只读 — EvolutionSlider 没有可逆操作 */}}
            disabled={loading}
          />
        </div>
      )}

      {/* R10.5.28: 升级可见化 banner. CD.txt 提"完全没看到前端重构了什么东西",
          显式在 UI 顶部列出本次 4 项核心升级, 让用户立刻看出 ScholarFlow 在
          这一版做了什么. 用 sessionStorage 记录"已阅", 关掉后再点 footer 链接
          重新显示. 4 个数据点: 安全 / 论文库 / 历史分路 / main.py 拆分. */}
      <R10_5_28Banner />

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
            // R10.5.30 (D5 P1-2): 多选论文 — Shift+click 凑 2 篇触发 CompareDrawer
            selectedPaperIds={selectedPaperIds}
            onTogglePaperSelection={togglePaperSelection}
            // R10.5.5: 最近搜索
            recentSearches={recentSearches}
            onClearRecent={clearRecentSearches}
            // R10.5.20: Runtime mode (mock/real) 切换
            runtimeMode={runtimeMode ?? undefined}
            onChangeRuntimeMode={handleChangeRuntimeMode}
            // R10.5.40 (Agent 1): 8 节点流水线状态条 — 喂 PipelineStrip 用.
            events={events}
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
          {/* R10.5.40 (Agent 1): focus 单栏模式隐藏 GraphPanel. 不卸载父容器,
              只是不渲染 GraphPanel 子节点 — 切回三栏时 GraphPanel 内部状态保留. */}
          {showGraph && (
            <GraphPanel
              graph={result?.citation_graph ?? null}
              // R10.5.5: 图谱节点 → 跨组件论文聚焦
              selectedPaperId={selectedPaperId}
              onSelectPaper={handleSelectPaper}
            />
          )}
        </div>
      </div>

      {/* R10.5.5: 快捷键面板 (按 ? 触发) */}
      {showShortcuts && <ShortcutsOverlay onClose={toggleShortcuts} />}

      {/* R10.5.3: 认证对话框 — 未登录时强制弹出 (OPEN_MODE=false).
          z-50 模态, 阻断所有下层交互, 防止用户绕过认证直接触发 search. */}
      {authState === 'unauthenticated' && (
        <LoginDialog
          requireAuth
          onSuccess={() => handleLoginSuccess(currentUser ?? ({} as UserInfo))}
        />
      )}

      {/* R10.5.28 (Holographic 集成): 分屏对比抽屉. 当用户多选恰好 2 篇论文时
          (selectedPaperIds.length === 2) 显示. reviews 暂传空对象, R10.5.29
          接 critic_agent 后端结果填充. R10.5.31 (F4): selectedPaperIds 走
          SelectionContext, 关闭时调 clearPaperSelection. */}
      {selectedPaperIds.length === 2 && result?.ranked_papers && (
        <CompareDrawer
          papers={result.ranked_papers as any}
          selectedPaperIds={selectedPaperIds}
          reviews={{}}
          onClose={clearPaperSelection}
        />
      )}

      {/* R10.5.28 (Holographic 集成): 全局命令面板 (Cmd+K / Ctrl+K 触发).
          R10.5.31 (F4): isOpen/onClose 走 UIContext, 不再用 useCommandPalette
          hook (避免双 Cmd+K 监听器 + 双 isOpen state). 13 个命令 handler
          见 handleCommand (11 真 + 2 stub). */}
      <CommandPalette
        isOpen={cmdPaletteOpen}
        onClose={closeCmdPalette}
        onExecuteCommand={handleCommand}
      />

      {/* R10.5.30 (D6 P1-3): 升级日志 modal — 永久 footer 链接触发.
          取代 R10.5.29 的一次性 R10_5_28Banner (sessionStorage 已阅, 关闭就看不到).
          这里 footer 链接永远在, 任何时候点开都能看到 8 项累积升级. */}
      <footer
        className="fixed bottom-2 right-3 z-40 font-ui"
        data-testid="changelog-footer"
      >
        <button
          type="button"
          onClick={openChangelog}
          className="text-[10px] font-mono uppercase tracking-[0.18em] px-2 py-1 opacity-60 hover:opacity-100 transition"
          style={{
            color: 'var(--sf-muted)',
            backgroundColor: 'var(--sf-bg-elev)',
            border: '1px solid var(--sf-border)',
          }}
          title="R10.5.31 累积升级日志 (CG.txt / CD.txt / F1-F6 deferred)"
          data-testid="changelog-footer-link"
        >
          ❦ R10.5.31 ❦
        </button>
      </footer>
      <ChangelogModal
        isOpen={changelogOpen}
        onClose={closeChangelog}
      />
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


// ===== R10.5.28: 升级可见化 banner =====
// CD.txt 反馈 "完全没看到前端重构了什么东西", 这一版我们用 sessionStorage
// 记录"已阅", 顶部显眼位置列出 4 项核心升级, 让用户一眼看出 ScholarFlow
// 在 R10.5.28 做了什么. 关闭后再点 footer 链接 (见 ? 帮助对话框) 重新展开.
// R10.5.51 cleanup (BACKLOG B-008): key 走 STORAGE_KEYS 中央化.
const R10_5_28_DISMISSED_KEY = STORAGE_KEYS.upgradeBannerDismissed;
const R10_5_28_NOTES: Array<{
  key: string;
  emoji: string;
  title: string;
  body: string;
  tag: string;
  tagColor: string;
}> = [
  {
    key: 'security',
    emoji: '🔐',
    title: 'API Key 存储加固',
    body: '长期 key 从 localStorage 降到 sessionStorage, 30 分钟无活动自动清空, 关浏览器即失效 — 缓解 XSS 偷走后长期有效的攻击窗口.',
    tag: 'CG.txt P1 #4',
    tagColor: 'var(--sf-accent)',
  },
  {
    key: 'local',
    emoji: '🧪',
    title: '本地论文库身份标识',
    body: '50+ 篇 mock 论文统一标 "本地演示" (紫色 badge), url 加 #demo=1, 一眼区分真实 Semantic Scholar / OpenAlex 跟本地演示数据.',
    tag: 'CD.txt 隐性问题',
    tagColor: 'rgb(168, 85, 247)',
  },
  {
    key: 'history',
    emoji: '🗂',
    title: '历史记录分本地 / 真实两路',
    body: '最近搜索按 source 字段分成 "全部 / 真实 (绿) / 本地 (紫)" 三 tab, 避免演示模式污染后用户分不清哪些是真检索结果.',
    tag: 'CD.txt 隐性问题',
    tagColor: 'rgb(168, 85, 247)',
  },
  {
    key: 'backend',
    emoji: '🧹',
    title: 'main.py 拆分 + config.py 去重',
    body: 'main.py 1140→1083 行, 抽 admin 路由到 routes/admin.py; config.py 删 _DOTENV / _getenv_ci 重复定义, 业务侧字段读取路径只剩一处.',
    tag: 'CG.txt P1 #5',
    tagColor: 'var(--sf-accent)',
  },
];

function R10_5_28Banner() {
  // 用 sessionStorage 而非 localStorage: 标签页关闭后再打开, banner 再显示一次
  // (新版本升级 / 关键变更需要让用户看到), 但当前 session 内关掉就关掉.
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(R10_5_28_DISMISSED_KEY) === '1';
    } catch {
      return false;
    }
  });
  const [expanded, setExpanded] = useState<boolean>(false);
  if (dismissed) return null;
  return (
    <div
      className="mx-4 sm:mx-6 mt-3 px-3 py-2.5 font-ui text-xs"
      style={{
        backgroundColor: 'var(--sf-bg-elev)',
        border: '1px solid var(--sf-border)',
        borderLeft: '3px solid var(--sf-accent)',
      }}
      data-testid="r10-5-28-banner"
    >
      <div className="flex items-center gap-3 flex-wrap">
        <span
          className="font-mono text-[10px] uppercase tracking-[0.18em] shrink-0"
          style={{ color: 'var(--sf-accent)' }}
        >
          R10.5.28
        </span>
        <span style={{ color: 'var(--sf-text)' }}>
          本次升级新增 <strong>4 项</strong>安全 + 可视化改进.
        </span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-[10px] font-mono uppercase tracking-[0.15em] opacity-70 hover:opacity-100 transition"
          style={{ color: 'var(--sf-muted)' }}
          data-testid="r10-5-28-banner-toggle"
        >
          {expanded ? '收起 ▲' : '查看详情 ▼'}
        </button>
        <button
          type="button"
          onClick={() => {
            try { sessionStorage.setItem(R10_5_28_DISMISSED_KEY, '1'); } catch { /* ignore */ }
            setDismissed(true);
          }}
          className="ml-auto font-display italic text-base leading-none opacity-50 hover:opacity-100 transition"
          style={{ color: 'var(--sf-muted)' }}
          aria-label="关闭升级公告"
          title="关闭 (sessionStorage 记录, 本次会话不再显示)"
        >
          ×
        </button>
      </div>
      {expanded && (
        <div
          className="mt-2.5 pt-2.5 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2.5 border-t"
          style={{ borderColor: 'var(--sf-border)' }}
        >
          {R10_5_28_NOTES.map((n) => (
            <div key={n.key} className="flex gap-2 items-start">
              <span className="text-base shrink-0 leading-snug">{n.emoji}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-1.5 flex-wrap">
                  <span
                    className="font-display text-[12px]"
                    style={{ color: 'var(--sf-text)' }}
                  >
                    {n.title}
                  </span>
                  <span
                    className="font-mono text-[8.5px] uppercase tracking-[0.12em] px-1 py-0.5 shrink-0"
                    style={{ backgroundColor: 'transparent', border: `1px solid ${n.tagColor}`, color: n.tagColor }}
                  >
                    {n.tag}
                  </span>
                </div>
                <p
                  className="font-body text-[11px] leading-snug mt-0.5"
                  style={{ color: 'var(--sf-muted)' }}
                >
                  {n.body}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

    </div>
  );
}
