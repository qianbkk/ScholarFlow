import { useEffect, useState } from 'react';
import type { Paper } from '../types';
import { fetchProviders, type ProviderInfo, type RuntimeMode } from '../services/api';
// R10.5.29 (simplify): 删 inline RecentEntry 类型, 改从 useSearch 导入. 避免
// 3 文件 (useSearch / QueryPanel / App) 各自定义 'local'|'real'|'unknown' 联合.
import type { RecentEntry, NodeEvent } from '../hooks/useSearch';
import { PipelineStrip } from './PipelineStrip';
// R10.5.51 cleanup (BACKLOG B-008): 改用 STORAGE_KEYS 中央化.
import { STORAGE_KEYS } from '../lib/storageKeys';

interface PipelineStep {
  key: string;
  label: string;
  emoji: string;
}

interface Props {
  loading: boolean;
  onSearch: (query: string, budget: number, maxIter: number, provider?: string) => void;
  onReset: () => void;
  papers: Paper[];
  lastQuery: string;
  currentStep?: number;
  elapsedSec?: number;
  pipelineSteps?: PipelineStep[];
  // Round 5 SIMPLIFY (API-001): 后端 M-1 已发 is_degraded_response + fallback_paper_count
  // 顶层字段, 前端直接用, 替代之前从 papers[].is_fallback 单篇聚合的 useMemo 派生.
  isDegradedResponse?: boolean;
  fallbackPaperCount?: number;
  // R10.5.5: 跨组件论文聚焦
  selectedPaperId?: string | null;
  onSelectPaper?: (paperId: string | null) => void;
  // R10.5.30 (D5 P1-2): 多选论文 — ⌘+click / Ctrl+click 加, 凑齐 2 篇触发 CompareDrawer
  selectedPaperIds?: string[];
  onTogglePaperSelection?: (paperId: string) => void;
  // R10.5.5: 最近搜索 (localStorage LRU 5 条)
  // R10.5.28 (CD.txt 修复): 类型改为 RecentEntry, 支持分本地/真实两路.
  // R10.5.29 (simplify): RecentEntry / RuntimeMode 都从 useSearch / services/api
  // 导入, 不再 inline 重复.
  recentSearches?: RecentEntry[];
  onClearRecent?: () => void;
  // R10.5.20: runtime mode (mock / real) 切换. App.tsx 持有 state + 拉/设 API,
  // 这里只接收 + emit.
  runtimeMode?: RuntimeMode;
  onChangeRuntimeMode?: (mode: RuntimeMode) => void;
  // R10.5.40 (Agent 1): 8 节点流水线事件流 — 喂 PipelineStrip 用.
  // App.tsx 从 useSearch.events 透传下来, QueryPanel 只 render 不加工.
  events?: NodeEvent[];
}

const SUGGESTIONS = [
  'transformer attention mechanism',
  '大语言模型在代码生成中的应用',
  'multi-agent reinforcement learning coordination',
  'retrieval augmented generation survey',
  'chain of thought reasoning in LLMs',
];

// R10.5.5: 表单状态 (budget / maxIter / provider) 跨刷新持久化
// 用户不需要每次都重新设预算 / 迭代次数 / provider, 提升"重复检索同一领域"的体验.
// R10.5.51 cleanup (BACKLOG B-008): key 走 STORAGE_KEYS 中央化.
const FORM_STORAGE_KEY = STORAGE_KEYS.formState;

interface PersistedForm {
  budget: number;
  maxIter: number;
  provider: string;
}

function loadFormState(): Partial<PersistedForm> {
  try {
    const raw = localStorage.getItem(FORM_STORAGE_KEY);
    if (!raw) return {};
    const obj = JSON.parse(raw);
    return typeof obj === 'object' && obj !== null ? obj : {};
  } catch {
    return {};
  }
}

function saveFormState(s: PersistedForm): void {
  try {
    localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(s));
  } catch {
    // 静默
  }
}

export function QueryPanel({
  loading, onSearch, onReset, papers, lastQuery,
  runtimeMode, onChangeRuntimeMode,
  currentStep = 0, elapsedSec = 0, pipelineSteps = [],
  isDegradedResponse = false, fallbackPaperCount = 0,
  selectedPaperId = null, onSelectPaper,
  // R10.5.30 (D5 P1-2): 多选 (Shift+click 凑 2 篇触发 CompareDrawer)
  selectedPaperIds = [], onTogglePaperSelection,
  recentSearches = [], onClearRecent,
  events = [],
}: Props) {
  // R10.5.5: 从 localStorage 恢复预算/迭代/provider 默认值
  const persisted = loadFormState();
  const [query, setQuery] = useState('');
  const [budget, setBudget] = useState<number>(typeof persisted.budget === 'number' ? persisted.budget : 2.0);
  const [maxIter, setMaxIter] = useState<number>(typeof persisted.maxIter === 'number' ? persisted.maxIter : 3);
  // LLM provider 选择 — 拉取后端 /providers 列表（仅 has_key=true 可见）
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [defaultProvider, setDefaultProvider] = useState<string>(persisted.provider || '');
  const [selectedProvider, setSelectedProvider] = useState<string>(persisted.provider || '');  // 空 = 用默认
  const [providersLoading, setProvidersLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setProvidersLoading(true);
    fetchProviders()
      .then((resp) => {
        if (cancelled) return;
        // R10 (M-16): provider 排序 — minimax 置顶, 其他保留后端原顺序.
        // 后端 _PROVIDER_META 顺序已经是 minimax 第一, 这里防御性再排一次 (前端不依赖后端顺序).
        const available = resp.providers.filter((p) => p.has_key);
        const sorted = [...available].sort((a, b) => {
          if (a.id === 'minimax') return -1;
          if (b.id === 'minimax') return 1;
          return 0;
        });
        setProviders(sorted);
        setDefaultProvider(resp.default_provider);
        // 初始化为默认 provider. 优先级: 持久化 > 后端 default_provider > 第一个.
        let def = sorted.find((p) => p.id === selectedProvider);  // 持久化的仍合法
        if (!def) def = sorted.find((p) => p.id === resp.default_provider);
        if (!def && sorted.length > 0) def = sorted[0];
        if (def) {
          setSelectedProvider(def.id);
          setDefaultProvider(def.id);
        }
      })
      .catch((err) => {
        // 静默失败：provider 下拉为空时回退到后端默认
        console.warn('fetchProviders failed:', err);
      })
      .finally(() => {
        if (!cancelled) setProvidersLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // R10.5.5: budget / maxIter / provider 变更即写 localStorage
  // (debounce 是不必要的 — 三个值都通过受控 input 触发, 量小)
  useEffect(() => {
    saveFormState({ budget, maxIter, provider: selectedProvider });
  }, [budget, maxIter, selectedProvider]);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    onSearch(query, budget, maxIter, selectedProvider || undefined);
  };

  const useSuggestion = (s: string) => {
    setQuery(s);
  };

  // R10.5.5: 点击最近搜索直接回填 + 自动触发检索
  // 比单纯回填更好: 用户意图明显, 立即重跑才是符合期望的行为
  const useRecent = (s: string) => {
    setQuery(s);
    setShowRecent(false);
    onSearch(s, budget, maxIter, selectedProvider || undefined);
  };

  const handleReset = () => {
    setQuery('');
    // budget/maxIter/provider 保留用户偏好 (持久化, 重置搜索时不清),
    // 这是符合预期的 — 用户改了预算希望下次还用
    onReset();
  };

  // R10.5.6 Fix: 表单可折叠 — 有结果时给论文列表腾空间
  // (旧版表单 + 示例 + 最近搜索 堆太满, 论文列表被挤出可视区)
  const [formCollapsed, setFormCollapsed] = useState<boolean>(false);
  // R10.5.20: 不再自动折叠. 旧逻辑 "hasResults && !loading → 折叠" 让用户搜索
  // 完必须点 "▾ 展开" 才能改 query 再搜, UX 不友好. 改成 "只响应用户主动折叠按钮",
  // 标题旁加 "再来一次" 快速重搜按钮.
  const hasResults = papers.length > 0;
  const shouldCollapseForm = formCollapsed;
  const [showRecent, setShowRecent] = useState<boolean>(false);  // 最近搜索 popover
  // R10.5.28 (CD.txt 隐性问题修复): 历史记录分本地 / 真实两路 tab 切换.
  // 'all' 显示全部, 'local' 只看本地 (mock / 演示), 'real' 只看真实 (真 API).
  const [recentTab, setRecentTab] = useState<'all' | 'local' | 'real'>('all');

  // R10.5.10 Fix: popover Esc 关闭 + 点外部关闭 (旧实现只有关闭 × 按钮, 用户
  // 点了某项后 popover 收起 (useRecent 设 false), 但若不点项只外面看, 没法关).
  useEffect(() => {
    if (!showRecent) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setShowRecent(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showRecent]);

  return (
    // Round 6 S5: 移动端 w-full, lg+ 切回 1/4 宽 + 280px 最小宽.
    // R10.5.4 Editorial: 右侧用 var(--sf-border) 印刷线分隔, 内部用 Newsreader 论文列表
    <aside
      className="w-full lg:w-1/4 lg:min-w-[280px] h-auto lg:h-full flex flex-col"
      style={{
        backgroundColor: 'var(--sf-bg)',
        borderRight: '1px solid var(--sf-border)',
      }}
    >
      {/* R10.5.40 (Agent 1): 8 节点流水线状态条 — 1 行, hairline bottom border,
          放在表单上方. 即使不在 loading 也显示 (IDLE 状态), 让用户始终能看到
          流水线结构. 跟 CockpitDashboard 不冲突 (后者只在 events.length>0 || loading 时显示
          横向 8 舱室; PipelineStrip 是静态 IDLE 占位 + 动态状态切换). */}
      <PipelineStrip
        events={events}
        currentStep={currentStep}
        loading={loading}
        hasError={!!recentSearches && false /* 错误状态由 CockpitDashboard 表达, 这里不重复 */}
      />
      <div
        className="px-3 py-2 border-b shrink-0"
        style={{ borderColor: 'var(--sf-border)' }}
        data-form-section
        data-collapsed={shouldCollapseForm ? 'true' : 'false'}
      >
        {/* 栏目标题 — Editorial 风格: 序号 + 衬线斜体 + "再来一次" 按钮 + 折叠按钮 */}
        <div className="flex items-baseline justify-between gap-2 mb-2">
          <div className="flex items-baseline gap-2 min-w-0">
            <span
              className="font-mono text-[10px] uppercase tracking-[0.18em] shrink-0"
              style={{ color: 'var(--sf-accent)' }}
            >
              § 1
            </span>
            <h2
              className="font-display text-base font-semibold italic truncate"
              style={{ color: 'var(--sf-text)' }}
            >
              研究查询
            </h2>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {/* R10.5.20: 搜索完成后, 标题旁加 "再来一次" 按钮让用户快速重搜
                (旧版自动折叠让用户感知不到 query 还可改) */}
            {hasResults && !loading && (
              <button
                type="button"
                onClick={() => submit()}
                disabled={!query.trim()}
                aria-label="用当前 query 重新检索"
                title="用当前 query 重新检索 (改 query 后点这里重跑)"
                data-testid="re-search-btn"
                className="font-mono text-[10px] uppercase tracking-[0.12em] px-1.5 py-0.5 transition-colors border shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                  color: 'var(--sf-accent)',
                  borderColor: 'var(--sf-accent)',
                }}
                onMouseEnter={(e) => {
                  if (query.trim()) {
                    e.currentTarget.style.backgroundColor = 'var(--sf-accent)';
                    e.currentTarget.style.color = 'var(--sf-bg)';
                  }
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent';
                  e.currentTarget.style.color = 'var(--sf-accent)';
                }}
              >
                ↻ 再来一次
              </button>
            )}
            <button
              type="button"
              onClick={() => setFormCollapsed((c) => !c)}
              aria-label={shouldCollapseForm ? '展开查询表单' : '折叠查询表单'}
              title={shouldCollapseForm ? '展开查询表单' : '折叠查询表单'}
              className="font-mono text-[10px] uppercase tracking-[0.12em] px-1.5 py-0.5 transition-colors border shrink-0"
              style={{
                color: 'var(--sf-muted)',
                borderColor: 'var(--sf-border)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--sf-accent)';
                e.currentTarget.style.borderColor = 'var(--sf-accent)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--sf-muted)';
                e.currentTarget.style.borderColor = 'var(--sf-border)';
              }}
            >
              {shouldCollapseForm ? '▾ 展开' : '▴ 折叠'}
            </button>
          </div>
        </div>
        {/* 折叠态: 单行紧凑摘要 (回填内容 + 折叠后保留一个快搜图标按钮) */}
        {shouldCollapseForm ? (
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setFormCollapsed(false)}
              data-search-input
              tabIndex={-1}
              className="flex-1 text-left font-body text-[12px] italic truncate px-2 py-1 transition-colors cursor-text"
              style={{
                backgroundColor: 'var(--sf-bg-elev)',
                color: query ? 'var(--sf-text)' : 'var(--sf-muted)',
                border: '1px solid var(--sf-border)',
              }}
              title="点击展开查询表单"
            >
              {query || '点击展开查询表单…'}
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={!query.trim() || loading}
              aria-label="重新检索"
              title="用当前 query 重新检索"
              className="font-display italic font-semibold px-2 py-1 text-[12px] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                backgroundColor: 'var(--sf-accent)',
                color: 'var(--sf-bg)',
              }}
            >
              ↻
            </button>
          </div>
        ) : (
        <form onSubmit={submit} className="space-y-2">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入研究问题…"
            rows={1}
            maxLength={2000}
            data-search-input
            className="w-full font-body text-[14px] leading-relaxed border rounded-none px-2.5 py-1.5 resize-none transition-colors"
            style={{
              // R10.5.20: 搜索完成 (有结果) 时边框高亮 accent 色, 暗示"可改 query 再搜"
              borderColor: hasResults && !loading ? 'var(--sf-accent)' : 'var(--sf-border)',
              borderWidth: hasResults && !loading ? '1.5px' : '1px',
              backgroundColor: 'var(--sf-bg)',
              color: 'var(--sf-text)',
              fontStyle: query ? 'normal' : 'italic',
            }}
            onKeyDown={(e) => {
              // Ctrl/Cmd+Enter 也提交 — 用户多行 query 时不能只靠表单 submit 按钮
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                submit();
              }
            }}
          />
          {/* Round 4 U3: 实时字符计数, 颜色用 CSS 变量 */}
          <div
            className="text-[10px] mt-0.5 text-right font-mono tracking-wider"
            style={{
              color:
                query.length >= 2000
                  ? 'var(--sf-accent)'
                  : query.length > 1800
                  ? 'var(--sf-accent)'
                  : 'var(--sf-muted)',
            }}
            aria-live="polite"
          >
            {query.length.toLocaleString()}/2,000
          </div>

          <div className="flex items-center gap-3 text-[11px] font-mono uppercase tracking-wider">
            <label className="flex items-center gap-1.5" style={{ color: 'var(--sf-muted)' }}>
              模型
              <select
                value={selectedProvider}
                onChange={(e) => setSelectedProvider(e.target.value)}
                disabled={providersLoading}
                title={providersLoading ? '加载中…' : '选择 LLM provider（仅显示已配置 key 的）'}
                className="font-mono text-[11px] tracking-normal border rounded-none px-1.5 py-0.5 max-w-[140px]"
                style={{
                  borderColor: 'var(--sf-border)',
                  backgroundColor: 'var(--sf-bg)',
                  color: 'var(--sf-text)',
                }}
              >
                {providers.length === 0 && !providersLoading && (
                  <option value="">（无可用 provider）</option>
                )}
                {providers.map((p) => {
                  if (p.verified === false) {
                    return (
                      <option
                        key={p.id}
                        value={p.id}
                        disabled={false}
                        title="API key 验证失败,请检查 .env 或重新生成"
                        style={{ color: 'var(--sf-accent)' }}
                      >
                        ✕ {p.name} (key 失效)
                      </option>
                    );
                  }
                  if (p.verified === null) {
                    return (
                      <option
                        key={p.id}
                        value={p.id}
                        disabled={true}
                        title="后端启动后 5s 内未完成 key 验证,稍候重试"
                        style={{ color: 'var(--sf-muted)' }}
                      >
                        ⏳ {p.name} (验证中)
                      </option>
                    );
                  }
                  const isDefault = p.id === 'minimax';
                  return (
                    <option
                      key={p.id}
                      value={p.id}
                      title={p.flagship_model}
                    >
                      {isDefault ? `★ ${p.name}` : p.name}
                    </option>
                  );
                })}
              </select>
            </label>
            <label className="flex items-center gap-1.5" style={{ color: 'var(--sf-muted)' }}>
              预算
              <input
                type="number"
                min={0.1}
                max={20}
                step={0.1}
                value={budget}
                onChange={(e) => setBudget(parseFloat(e.target.value) || 2.0)}
                className="font-mono text-[11px] tracking-normal border rounded-none w-14 px-1.5 py-0.5 text-center tabular-nums"
                style={{
                  borderColor: 'var(--sf-border)',
                  backgroundColor: 'var(--sf-bg)',
                  color: 'var(--sf-text)',
                }}
              />
            </label>
            <label className="flex items-center gap-1.5" style={{ color: 'var(--sf-muted)' }}>
              迭代
              <input
                type="number"
                min={1}
                max={5}
                value={maxIter}
                onChange={(e) => setMaxIter(parseInt(e.target.value) || 3)}
                className="font-mono text-[11px] tracking-normal border rounded-none w-12 px-1.5 py-0.5 text-center tabular-nums"
                style={{
                  borderColor: 'var(--sf-border)',
                  backgroundColor: 'var(--sf-bg)',
                  color: 'var(--sf-text)',
                }}
              />
            </label>
          </div>

          {/* R10.5.20: Mock / Real 数据源切换 (前端 UI 控制)
              后端 /admin/runtime-mode 改 _runtime_mode_override, 业务函数查
              is_runtime_mock() 走 mock 路径. 切换即时生效, 无需重启. */}
          {onChangeRuntimeMode && runtimeMode && (
            <div
              className="flex items-center gap-3 text-[10.5px] font-mono uppercase tracking-wider pt-0.5"
              data-testid="runtime-mode-toggle"
            >
              <span style={{ color: 'var(--sf-muted)' }}>数据源</span>
              <label className="flex items-center gap-1 cursor-pointer" title="Mock 数据: 内置论文, 无网络, 不烧钱">
                <input
                  type="radio"
                  name="runtime-mode"
                  value="mock"
                  checked={runtimeMode === 'mock'}
                  onChange={() => onChangeRuntimeMode('mock')}
                  disabled={loading}
                  data-testid="runtime-mode-mock"
                  className="cursor-pointer disabled:cursor-not-allowed"
                  style={{ accentColor: 'var(--sf-accent)' }}
                />
                <span style={{ color: runtimeMode === 'mock' ? 'var(--sf-accent)' : 'var(--sf-text)' }}>
                  演示
                </span>
              </label>
              <label className="flex items-center gap-1 cursor-pointer" title="真实 API: Semantic Scholar + OpenAlex, 需要 key">
                <input
                  type="radio"
                  name="runtime-mode"
                  value="real"
                  checked={runtimeMode === 'real'}
                  onChange={() => onChangeRuntimeMode('real')}
                  disabled={loading}
                  data-testid="runtime-mode-real"
                  className="cursor-pointer disabled:cursor-not-allowed"
                  style={{ accentColor: 'var(--sf-accent)' }}
                />
                <span style={{ color: runtimeMode === 'real' ? 'var(--sf-accent)' : 'var(--sf-text)' }}>
                  真实
                </span>
              </label>
            </div>
          )}

          <div className="flex items-stretch gap-0">
            {loading ? (
              <button
                type="button"
                onClick={onReset}
                aria-label="取消当前搜索"
                title="点击中断当前检索流水线"
                className="flex-1 text-sm font-medium py-2 transition-colors"
                style={{
                  backgroundColor: 'var(--sf-text)',
                  color: 'var(--sf-bg)',
                }}
              >
                取消
              </button>
            ) : (
              <button
                type="submit"
                disabled={!query.trim()}
                aria-label="开始搜索"
                title={!query.trim() ? '请先输入研究问题' : '开始检索'}
                className="flex-1 text-sm font-display italic font-semibold py-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                  backgroundColor: 'var(--sf-accent)',
                  color: 'var(--sf-bg)',
                }}
              >
                检索 →
              </button>
            )}
            <button
              type="button"
              onClick={handleReset}
              disabled={loading}
              className="px-3 text-sm border-l transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                borderColor: 'var(--sf-border)',
                color: 'var(--sf-muted)',
              }}
              title={loading ? '请先取消当前搜索' : '清空表单'}
            >
              清空
            </button>
            {recentSearches.length > 0 && (
              <button
                type="button"
                onClick={() => setShowRecent((s) => !s)}
                aria-label="最近搜索"
                aria-expanded={showRecent}
                title="最近搜索"
                className="px-2 py-1.5 text-sm transition-colors border-l"
                style={{
                  color: showRecent ? 'var(--sf-accent)' : 'var(--sf-muted)',
                  borderColor: 'var(--sf-border)',
                }}
              >
                ⏱
              </button>
            )}
          </div>
        </form>
        )}

        {/* 加载进度条 — Editorial 风格: 8 段细线 + 当前节点标签 */}
        {loading && (
          <div
            className="mt-3 p-2.5"
            role="status"
            aria-live="polite"
            aria-label="搜索进行中"
            style={{
              backgroundColor: 'var(--sf-bg-elev)',
              border: '1px solid var(--sf-border)',
            }}
          >
            <div
              className="flex items-baseline justify-between text-[10px] font-mono uppercase tracking-[0.12em] mb-2"
              style={{ color: 'var(--sf-accent)' }}
            >
              <span>
                {pipelineSteps[currentStep]?.emoji} {pipelineSteps[currentStep]?.label}
              </span>
              <span className="tabular-nums">{elapsedSec.toFixed(1)}s</span>
            </div>
            <div className="grid grid-cols-8 gap-0.5">
              {pipelineSteps.map((s, i) => (
                <div
                  key={s.key}
                  className="h-0.5"
                  style={{
                    backgroundColor:
                      i < currentStep
                        ? 'var(--sf-accent)'
                        : i === currentStep
                        ? 'var(--sf-accent)'
                        : 'var(--sf-border)',
                    opacity: i <= currentStep ? 1 : 0.5,
                    animation: i === currentStep ? 'sf-fade 1.2s ease infinite alternate' : undefined,
                  }}
                />
              ))}
            </div>
          </div>
        )}

        {/* 示例 — 只在表单未折叠 + query 为空时显示, 折起后论文列表占满
            R10.5.10 Fix: 紧凑 padding, 论文列表可点更多行 */}
        {!query && !shouldCollapseForm && (
          <div className="mt-1.5 flex flex-wrap gap-x-1.5 gap-y-0.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => useSuggestion(s)}
                className="text-[10px] font-body italic transition-colors border-b border-dashed"
                style={{
                  color: 'var(--sf-muted)',
                  borderColor: 'var(--sf-border)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = 'var(--sf-accent)';
                  e.currentTarget.style.borderColor = 'var(--sf-accent)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = 'var(--sf-muted)';
                  e.currentTarget.style.borderColor = 'var(--sf-border)';
                }}
                title={s}
              >
                {s.length > 20 ? s.slice(0, 20) + '…' : s}
              </button>
            ))}
          </div>
        )}

        {/* R10.5.6 Fix: 最近搜索 popover — 不再常驻, 点 ⏱ 按钮才展开
            旧版 always-visible 块 + 5 个示例 + 表单 = 论文列表被挤出可视区.
            改 popover 后, 论文列表始终优先占满剩余高度. */}
        {showRecent && recentSearches.length > 0 && (
          <div
            className="mt-2 p-2 font-ui"
            style={{
              backgroundColor: 'var(--sf-bg-elev)',
              border: '1px solid var(--sf-border)',
            }}
            data-testid="recent-popover"
          >
            <div className="flex items-center justify-between mb-1.5">
              <p
                className="text-[9px] uppercase tracking-[0.18em] font-mono"
                style={{ color: 'var(--sf-muted)' }}
              >
                最近搜索
              </p>
              <div className="flex items-center gap-2">
                {onClearRecent && (
                  <button
                    type="button"
                    onClick={onClearRecent}
                    className="text-[9px] font-mono uppercase tracking-[0.15em] opacity-60 hover:opacity-100 transition"
                    style={{ color: 'var(--sf-muted)' }}
                    title="清除全部最近搜索"
                  >
                    清除
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setShowRecent(false)}
                  className="font-display italic text-base leading-none opacity-60 hover:opacity-100 transition"
                  style={{ color: 'var(--sf-muted)' }}
                  aria-label="关闭"
                >
                  ×
                </button>
              </div>
            </div>
            {/* R10.5.28 (CD.txt 隐性问题修复): 本地 / 真实 / 全部 tab.
                用户能区分哪些搜索走的是真实 API, 哪些是 mock 演示. */}
            <div className="flex items-center gap-1 mb-1.5" data-testid="recent-tab-row">
              {(['all', 'real', 'local'] as const).map((t) => {
                const count =
                  t === 'all'
                    ? recentSearches.length
                    : recentSearches.filter((e) => e.source === t).length;
                const isActive = recentTab === t;
                const color =
                  t === 'local'
                    ? 'rgb(168, 85, 247)'   // 紫 = 本地演示
                    : t === 'real'
                    ? 'rgb(34, 197, 94)'    // 绿 = 真实
                    : 'var(--sf-muted)';
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setRecentTab(t)}
                    className="text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 border transition-colors"
                    style={{
                      borderColor: isActive ? color : 'var(--sf-border)',
                      color: isActive ? color : 'var(--sf-muted)',
                      backgroundColor: isActive ? 'transparent' : 'transparent',
                      fontWeight: isActive ? 600 : 400,
                    }}
                    data-testid={`recent-tab-${t}`}
                  >
                    {t === 'all' ? '全部' : t === 'real' ? '真实' : '本地'} ({count})
                  </button>
                );
              })}
            </div>
            <div className="space-y-0.5">
              {recentSearches
                .filter((e) => recentTab === 'all' || e.source === recentTab)
                .map((entry, i) => (
                <button
                  key={`${entry.query}-${i}`}
                  type="button"
                  onClick={() => useRecent(entry.query)}
                  className="group flex items-center gap-2 w-full text-left px-1.5 py-1 transition-colors"
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--sf-bg)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title={entry.query}
                >
                  <span
                    className="font-mono text-[9px] tabular-nums shrink-0 w-4"
                    style={{ color: 'var(--sf-muted)' }}
                  >
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span
                    className="font-body text-[12px] flex-1 min-w-0 truncate"
                    style={{ color: 'var(--sf-text)' }}
                  >
                    {entry.query}
                  </span>
                  {/* R10.5.28 (CD.txt 修复): 每条历史右侧 source 小标签 */}
                  {entry.source === 'real' && (
                    <span
                      className="font-mono text-[8px] uppercase tracking-wider px-1 py-0.5 shrink-0"
                      style={{ backgroundColor: 'rgba(34, 197, 94, 0.12)', color: 'rgb(34, 197, 94)' }}
                      data-testid="recent-source-real"
                    >真实</span>
                  )}
                  {entry.source === 'local' && (
                    <span
                      className="font-mono text-[8px] uppercase tracking-wider px-1 py-0.5 shrink-0"
                      style={{ backgroundColor: 'rgba(168, 85, 247, 0.12)', color: 'rgb(168, 85, 247)' }}
                      data-testid="recent-source-local"
                    >本地</span>
                  )}
                  <span
                    className="font-mono text-[9px] opacity-0 group-hover:opacity-100 transition shrink-0"
                    style={{ color: 'var(--sf-accent)' }}
                  >
                    ↵
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {isDegradedResponse && (
          <div
            className="mx-3 mt-3 p-3 flex items-start gap-3"
            role="alert"
            data-testid="degraded-banner"
            style={{
              backgroundColor: 'var(--sf-bg-elev)',
              borderLeft: '3px solid var(--sf-accent)',
            }}
          >
            <span
              className="font-display italic text-lg leading-none"
              style={{ color: 'var(--sf-accent)' }}
              role="img"
              aria-label="warning"
            >
              ⚠
            </span>
            <div className="flex-1 min-w-0">
              <h4
                className="font-display italic text-sm font-semibold"
                style={{ color: 'var(--sf-text)' }}
              >
                部分结果来自后备数据
              </h4>
              <p
                className="text-[11px] font-body mt-1 leading-relaxed"
                style={{ color: 'var(--sf-muted)' }}
              >
                本次搜索 {fallbackPaperCount} 篇论文触发后备 fallback
                (LLM API 限流 / key 失效 / 网络问题).
              </p>
              <details className="mt-2 text-[11px] font-ui">
                <summary
                  className="cursor-pointer select-none"
                  style={{ color: 'var(--sf-accent)' }}
                >
                  查看诊断与修复建议
                </summary>
                <ul
                  className="mt-1.5 space-y-1 pl-3 list-none"
                  style={{ color: 'var(--sf-muted)' }}
                >
                  {fallbackPaperCount >= 10 && (
                    <li className="relative pl-3">
                      <span
                        className="absolute left-0 top-0.5"
                        style={{ color: 'var(--sf-accent)' }}
                      >·</span>
                      <strong>Semantic Scholar 限流</strong>:
                      无 key 时免费配额 100 req/5min, 单次 max_iter=3 × 5 子查询 = 15+ 请求.
                      修复: <code className="font-mono">.env</code> 设{' '}
                      <code className="font-mono">SEMANTIC_SCHOLAR_API_KEY=xxx</code>.
                    </li>
                  )}
                  <li className="relative pl-3">
                    <span
                      className="absolute left-0 top-0.5"
                      style={{ color: 'var(--sf-accent)' }}
                    >·</span>
                    <strong>LLM 失败降级</strong>:
                    synthesis 节点 fallback 让综述质量降低 (评分统一 ~4.0).
                    可尝试: 换 provider (kimi/glm 备选); 降低 max_iterations.
                  </li>
                  <li className="relative pl-3">
                    <span
                      className="absolute left-0 top-0.5"
                      style={{ color: 'var(--sf-accent)' }}
                    >·</span>
                    <strong>网络/代理</strong>:
                    确认 <code className="font-mono">get_proxy()</code> 探测到的代理可达
                    (国内常见 7890/7897), SS/OpenAlex 走不通也会触发 fallback.
                  </li>
                </ul>
              </details>
            </div>
          </div>
        )}
        {/* 论文列表标题 — Editorial 风格: 序号 + 衬线斜体 (R10.5.10: 紧凑) */}
        <div
          className="px-3 py-1.5 sticky top-0 flex items-baseline justify-between border-b"
          style={{
            backgroundColor: 'var(--sf-bg-elev)',
            borderColor: 'var(--sf-border)',
          }}
        >
          <div className="flex items-baseline gap-2">
            <span
              className="font-mono text-[9px] uppercase tracking-[0.18em]"
              style={{ color: 'var(--sf-accent)' }}
            >
              § 2
            </span>
            <h3
              className="font-display text-[13px] italic font-semibold"
              style={{ color: 'var(--sf-text)' }}
            >
              论文列表 {papers.length > 0 && `(${papers.length})`}
            </h3>
          </div>
          {papers.length > 0 && (
            <span
              className="text-[9px] font-mono uppercase tracking-[0.12em]"
              style={{ color: 'var(--sf-muted)' }}
            >
              按相关性 · 点击打开
            </span>
          )}
        </div>
        {lastQuery && papers.length === 0 && (
          <div
            className="p-4 text-center space-y-3"
            data-testid="empty-search-state"
          >
            <p
              className="text-xs font-body italic"
              style={{ color: 'var(--sf-muted)' }}
            >
              未找到论文
            </p>
            <p
              className="text-[10px] font-mono uppercase tracking-[0.15em]"
              style={{ color: 'var(--sf-muted)' }}
            >
              试试更短 / 更宽泛 / 关键词变体
            </p>
            {/* R10.5.27 UX: 一键重试示例, 让空结果状态可恢复.
                点击直接用 setQuery + 自动触发 search, 不需要用户再敲. */}
            <div className="flex flex-wrap gap-1.5 justify-center pt-1">
              {[
                'transformer 综述',
                'attention mechanism',
                'large language model',
              ].map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => {
                    setQuery(example);
                    // R10.5.27 UX: 一键示例 query, 复用当前表单参数 (预算/迭代/provider),
                    // 用户不用再敲 textarea 也不用调整 settings.
                    onSearch(example, budget, maxIter, selectedProvider || undefined);
                  }}
                  className="font-mono text-[10px] uppercase tracking-[0.1em] px-2 py-1 border transition-colors"
                  style={{
                    borderColor: 'var(--sf-border)',
                    color: 'var(--sf-muted)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--sf-accent)';
                    e.currentTarget.style.color = 'var(--sf-accent)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--sf-border)';
                    e.currentTarget.style.color = 'var(--sf-muted)';
                  }}
                  data-testid="empty-search-chip"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}
        {/* 论文列表 — Editorial: 序号用 Fraunces 衬线斜体 (像脚注编号),
            标题用 Newsreader 15px 衬线 (长阅读), 元数据 mono + 细线分隔. */}
        <ul>
          {papers.map((p, i) => {
            // R10.5.30 (D5 P1-2): 同名变量已在上面 map 内, 删除这个外层 shadow
            const isSelected = p.paper_id && p.paper_id === selectedPaperId;
            // R10.5.30 (D5 P1-2): 多选高亮 — Shift+click 凑齐 2 篇时 CompareDrawer 自动显示
            const isMultiSelected = p.paper_id && (selectedPaperIds || []).includes(p.paper_id);
            return (
              <li
                key={p.paper_id || i}
                className="px-3 py-2 cursor-pointer transition-colors border-b"
                style={{
                  borderColor: 'var(--sf-border)',
                  // 多选用紫色左边框区分
                  borderLeft: isMultiSelected
                    ? '3px solid rgb(168, 85, 247)'
                    : isSelected
                    ? '3px solid var(--sf-accent)'
                    : '3px solid transparent',
                  backgroundColor: isSelected ? 'var(--sf-bg-elev)' : undefined,
                  paddingLeft: (isSelected || isMultiSelected) ? '13px' : '16px',
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--sf-bg-elev)';
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent';
                }}
                onClick={(e) => {
                  // R10.5.5: 单击只高亮 (跨组件聚焦), 不跳转
                  // 双击或按住 Ctrl/Cmd 单击才打开 URL — 跟 GraphPanel 约定一致
                  const wantsOpen = e.ctrlKey || e.metaKey || e.detail > 1;
                  if (wantsOpen) {
                    // BUG-003 / VULN-004 修复：URL 协议白名单 + noopener/noreferrer
                    if (p.url && /^https?:\/\//i.test(p.url)) {
                      window.open(p.url, '_blank', 'noopener,noreferrer');
                    }
                    return;
                  }
                  if (p.paper_id && onSelectPaper) {
                    // R10.5.30 (D5 P1-2): Shift+click 多选 (凑 2 篇触发 CompareDrawer).
                    if (e.shiftKey && onTogglePaperSelection) {
                      onTogglePaperSelection(p.paper_id);
                    } else {
                      onSelectPaper(isSelected ? null : p.paper_id);
                    }
                  }
                }}
                title={`${p.title}\n单击 = 跨组件聚焦 · Shift+单击 = 多选 (凑齐 2 篇触发对比) · 双击 / Ctrl+单击 = 打开论文`}
              >
                <div className="flex items-start gap-2.5">
                  <span
                    className="font-display italic text-sm leading-tight shrink-0 w-5 text-right tabular-nums"
                    style={{ color: 'var(--sf-accent)' }}
                  >
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start gap-1.5">
                      <p
                        className="font-body text-[14px] line-clamp-2 leading-snug flex-1"
                        style={{ color: 'var(--sf-text)' }}
                      >
                        {p.title}
                      </p>
                      {p.is_fallback && (
                        <span
                          className="shrink-0 font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5"
                          style={{
                            backgroundColor: 'var(--sf-accent-soft)',
                            color: 'var(--sf-accent)',
                          }}
                          title="此论文来自后备 fallback 数据"
                          data-testid="paper-fallback-badge"
                        >
                          fallback
                        </span>
                      )}
                      {/* R10.5.28 (CD.txt 修复): 本地演示数据来源标识.
                          mock_data → local_papers_db 包装后 source="local_demo".
                          前端一眼看出"这是本地演示, 非真实检索结果". */}
                      {p.source === 'local_demo' && (
                        <span
                          className="shrink-0 font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5"
                          style={{
                            backgroundColor: 'rgba(168, 85, 247, 0.15)',  // 紫色: 演示
                            color: 'rgb(168, 85, 247)',
                            border: '1px solid rgba(168, 85, 247, 0.4)',
                          }}
                          title="此论文来自本地演示数据库 (R10.5.28: mock_data 包装层), 非真实 Semantic Scholar / OpenAlex 检索结果"
                          data-testid="paper-local-demo-badge"
                        >
                          本地演示
                        </span>
                      )}
                    </div>
                    <div
                      className="flex items-center gap-2 mt-1 text-[10px] font-mono uppercase tracking-wider"
                      style={{ color: 'var(--sf-muted)' }}
                    >
                      <span className="tabular-nums">{p.year || '—'}</span>
                      <span style={{ color: 'var(--sf-border)' }}>·</span>
                      <span className="tabular-nums">{p.citation_count.toLocaleString()} cite</span>
                      <span style={{ color: 'var(--sf-border)' }}>·</span>
                      <span
                        className="tabular-nums font-semibold"
                        style={{ color: 'var(--sf-accent)' }}
                      >
                        ★{p.final_score.toFixed(1)}
                      </span>
                      {p.is_expanded && (
                        <span
                          className="ml-auto text-[9px] font-mono uppercase tracking-wider px-1"
                          style={{
                            borderLeft: '2px solid var(--sf-accent)',
                            color: 'var(--sf-accent)',
                          }}
                        >
                          ext
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}
