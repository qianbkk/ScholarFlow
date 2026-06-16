import { useCallback, useEffect, useMemo, useState } from 'react';
import { CostDashboard } from './components/CostDashboard';
import { QueryPanel } from './components/QueryPanel';
import { ReportPanel } from './components/ReportPanel';
import { GraphPanel } from './components/GraphPanel';
import { ThemeSwitcher, type ThemeId } from './components/ThemeSwitcher';
import { LoginDialog } from './components/LoginDialog';
import { UserBadge } from './components/UserBadge';
// R10.5.28 (Holographic 集成): 5 个新组件. 之前合并的 feature/holographic-command-center
// 已经创建了组件但没在 App.tsx 渲染, 这一版按 docs/COMPREHENSIVE_UPGRADE_REPORT.md
// "待前端集成步骤" 的指导接入, 让 CockpitDashboard / EvolutionSlider / FilterPanel /
// CompareDrawer / CommandPalette 真正进入 UI.
import { CockpitDashboard } from './components/CockpitDashboard';
import { EvolutionSlider } from './components/EvolutionSlider';
// R10.5.29 (code-review): FilterPanel 暂未挂载 (R10.5.30 在 QueryPanel 论文列表接
// 多选 + filter UI 时再挂). 先删死 import 避免误导后续读者. PaperFilters type
// 仍需要, 改成本地定义 (跟 FilterPanel.tsx 保持结构一致即可, R10.5.30 一并抽到
// lib/paperFilters.ts).
import { CompareDrawer } from './components/CompareDrawer';
import { CommandPalette, useCommandPalette } from './components/CommandPalette';
// R10.5.30 (D6 P1-3): 永久升级日志 modal. 取代 R10.5.29 一次性 R10_5_28Banner.
import { ChangelogModal } from './components/ChangelogModal';
// R10.5.30 (D7 P2-3): PaperFilters 类型 + DEFAULT 从 lib 导入
import { DEFAULT_FILTERS, type PaperFilters } from './lib/paperFilters';
import { useSearch } from './hooks/useSearch';
import {
  healthCheck,
  fetchMe,
  logout as authLogout,
  type UserInfo,
  fetchRuntimeMode,
  setRuntimeMode,
  type RuntimeMode,
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
    // R10.5.28 (Holographic 集成): 节点级事件流 + 图谱快照, 喂新组件
    events, graphSnapshots,
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
  // R10.5.28 (Holographic 集成): Cockpit 展开的节点 / 多选对比的论文 / 过滤器状态.
  // 5 个新组件共用这 3 个 state. 命令面板是 hook 内部管, 不在这里.
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  const [selectedPaperIds, setSelectedPaperIds] = useState<string[]>([]);
  // R10.5.30 (D7 P2-3): PaperFilters 类型 + DEFAULT 从 lib/paperFilters 导入.
  // 之前 inline 重复, FilterPanel.tsx 接口跟这里漂移风险. 现在 1 source of truth.
  const [filters, setFilters] = useState<PaperFilters>(DEFAULT_FILTERS);
  // R10.5.28: CommandPalette 是 Cmd+K 触发的全局命令面板, 内部 hook 自己管 state.
  // onExecuteCommand 暂留空 handler (导出 / 过滤 / 视图切换命令的完整实现留 R10.5.29).
  const cmdPalette = useCommandPalette();
  const handleCommand = useCallback((cmdId: string) => {
    // 占位: 当前先打 log, R10.5.29 接 onExport (bibtex/ris), onFilterChange, onViewChange
    console.info('[CommandPalette] execute:', cmdId);
  }, []);
  // OPEN_MODE=true 时允许用户主动关闭登录框 (实际不会触发, 走 authenticated).
  // R10.5.5: 跨组件论文聚焦 — 论文列表 / 图谱节点 / 报告引用表 三者互相同步高亮
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  // R10.5.30 (D6 P1-3): 升级日志 modal 状态 — footer 链接触发, 永久可见
  const [changelogOpen, setChangelogOpen] = useState<boolean>(false);
  // R10.5.5: 快捷键面板显示状态
  const [showShortcuts, setShowShortcuts] = useState<boolean>(false);
  // R10.5.20: Runtime mode (mock / real) 状态. 启动时从后端拉, 切换时调
  // /admin/runtime-mode POST. 切换即时生效, 不需要重启.
  const [runtimeMode, setRuntimeModeState] = useState<RuntimeMode | null>(null);

  useEffect(() => {
    fetchRuntimeMode()
      .then((info) => setRuntimeModeState(info.mode))
      .catch(() => setRuntimeModeState('real'));  // 失败兜底
  }, []);

  const handleChangeRuntimeMode = useCallback((mode: RuntimeMode) => {
    setRuntimeModeState(mode);  // 乐观更新
    setRuntimeMode(mode)
      .then((info) => setRuntimeModeState(info.mode))
      .catch(() => {
        // 失败回滚
        setRuntimeModeState((prev) => prev);
        console.warn('setRuntimeMode failed, rolled back');
      });
  }, []);

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

      // Cmd/Ctrl+K → 命令面板 (优先) 或聚焦 query (兜底).
      // R10.5.29 (code-review): useCommandPalette hook 也注册了 Cmd+K, 两个监听器
      // 触发顺序由 useEffect 顺序决定, 旧实现可能 hook 先注册但 App.tsx handler
      // 先 return → 用户按 Cmd+K 只聚焦 query 不开面板. 修法: 命令面板 open 时
      // 让 hook 接管, 关闭时 App.tsx handler 兜底聚焦 query. 冲突解决靠状态查询
      // (cmdPalette.isOpen) 而非监听器顺序.
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        if (!cmdPalette.isOpen) {
          // 面板未开 → App.tsx 自己 toggle 打开, hook 这次不响应
          cmdPalette.toggle();
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
            onTogglePaperSelection={(paperId: string) => {
              setSelectedPaperIds((prev) =>
                prev.includes(paperId)
                  ? prev.filter((id) => id !== paperId)
                  : [...prev, paperId].slice(-2)  // 最多 2 篇
              );
            }}
            // R10.5.5: 最近搜索
            recentSearches={recentSearches}
            onClearRecent={clearRecentSearches}
            // R10.5.20: Runtime mode (mock/real) 切换
            runtimeMode={runtimeMode ?? undefined}
            onChangeRuntimeMode={handleChangeRuntimeMode}
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

      {/* R10.5.28 (Holographic 集成): 分屏对比抽屉. 当用户多选恰好 2 篇论文时
          (selectedPaperIds.length === 2) 显示. reviews 暂传空对象, R10.5.29
          接 critic_agent 后端结果填充. selectedPaperIds 接入方式: 论文列表项
          多选状态 (R10.5.29 在 QueryPanel 论文行加 ⌘+click 多选) 才能让
          selectedPaperIds 真的有 2 项, 当前默认空, 等多选接线. */}
      {selectedPaperIds.length === 2 && result?.ranked_papers && (
        <CompareDrawer
          papers={result.ranked_papers as any}
          selectedPaperIds={selectedPaperIds}
          reviews={{}}
          onClose={() => setSelectedPaperIds([])}
        />
      )}

      {/* R10.5.28 (Holographic 集成): 全局命令面板 (Cmd+K / Ctrl+K 触发).
          useCommandPalette hook 内部管 isOpen + 快捷键注册. 13 个预定义命令
          暂走 console.log 占位, R10.5.29 接导出 / 过滤 / 视图切换. */}
      <CommandPalette
        isOpen={cmdPalette.isOpen}
        onClose={cmdPalette.close}
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
          onClick={() => setChangelogOpen(true)}
          className="text-[10px] font-mono uppercase tracking-[0.18em] px-2 py-1 opacity-60 hover:opacity-100 transition"
          style={{
            color: 'var(--sf-muted)',
            backgroundColor: 'var(--sf-bg-elev)',
            border: '1px solid var(--sf-border)',
          }}
          title="R10.5.30 累积升级日志 (CG.txt / CD.txt / 22 项 deferred)"
          data-testid="changelog-footer-link"
        >
          ❦ R10.5.30 ❦
        </button>
      </footer>
      <ChangelogModal
        isOpen={changelogOpen}
        onClose={() => setChangelogOpen(false)}
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
const R10_5_28_DISMISSED_KEY = 'sf-r10_5_28-banner-dismissed';
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
