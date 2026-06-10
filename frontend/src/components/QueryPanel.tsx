import { useEffect, useState } from 'react';
import type { Paper } from '../types';
import { fetchProviders, type ProviderInfo } from '../services/api';

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
}

const SUGGESTIONS = [
  'transformer attention mechanism',
  '大语言模型在代码生成中的应用',
  'multi-agent reinforcement learning coordination',
  'retrieval augmented generation survey',
  'chain of thought reasoning in LLMs',
];

export function QueryPanel({
  loading, onSearch, onReset, papers, lastQuery,
  currentStep = 0, elapsedSec = 0, pipelineSteps = [],
  isDegradedResponse = false, fallbackPaperCount = 0,
}: Props) {
  const [query, setQuery] = useState('');
  const [budget, setBudget] = useState(2.0);
  const [maxIter, setMaxIter] = useState(3);
  // LLM provider 选择 — 拉取后端 /providers 列表（仅 has_key=true 可见）
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [defaultProvider, setDefaultProvider] = useState<string>('');
  const [selectedProvider, setSelectedProvider] = useState<string>('');  // 空 = 用默认
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
        // 初始化为默认 provider (minimax 优先, 后端 default 次之, 最后空字符串)
        // 旧逻辑: 用后端 default_provider 字段; 但 .env 可能配了 minimax 没 key,
        // 那时 default_provider='minimax' 但 has_key=false, 默认 fallback 到第一个有 key 的.
        let def = sorted.find(
          (p) => p.id === resp.default_provider
        );
        if (!def && sorted.length > 0) {
          def = sorted[0];  // 第一个 (排序后 minimax 优先)
        }
        if (def) setSelectedProvider(def.id);
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

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    onSearch(query, budget, maxIter, selectedProvider || undefined);
  };

  const useSuggestion = (s: string) => {
    setQuery(s);
  };

  const handleReset = () => {
    setQuery("");
    setBudget(2.0);
    setMaxIter(3);
    setSelectedProvider(defaultProvider);
    onReset();
  };

  return (
    // Round 6 S5: 移动端 w-full, lg+ 切回 1/4 宽 + 280px 最小宽.
    // 高度也变 h-auto (移动端跟随内容) vs h-full (桌面 flex 子项填满).
    <aside className="w-full lg:w-1/4 lg:min-w-[280px] h-auto lg:h-full bg-[var(--sf-bg)] border-r border-slate-200 flex flex-col">
      <div className="p-3 border-b border-slate-100">
        <h2 className="text-sm font-semibold text-slate-700 mb-2">研究查询</h2>
        <form onSubmit={submit} className="space-y-2">
          {/* Round 6 S4': 三个英文点 "..." → Unicode 省略号 "…", 符合中文排版规范.
              R4 后 QueryPanel.tsx 残留 "（中英文均可）..." 等半角 ellipsis,
              与 R5 新加的 "加载中…" 风格不一致. 统一改用 U+2026. */}
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入研究问题（中英文均可）…"
            rows={2}
            maxLength={2000}
            className="w-full text-sm border border-slate-300 rounded-md p-2 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent resize-none"
          />
          {/* Round 4 U3: 实时字符计数，防止超长 query 触发后端 400
              > 1800 变橙色（警告接近上限），= 2000 变红色（已到硬上限）。 */}
          <div
            className={`text-xs mt-1 text-right ${
              query.length >= 2000
                ? 'text-red-600 font-medium'
                : query.length > 1800
                ? 'text-orange-500'
                : 'text-slate-400'
            }`}
            aria-live="polite"
          >
            {query.length}/2000
          </div>

          <div className="flex items-center gap-2 text-xs">
            <label className="flex items-center gap-1 text-slate-600">
              模型
              <select
                value={selectedProvider}
                onChange={(e) => setSelectedProvider(e.target.value)}
                disabled={providersLoading}
                title={providersLoading ? '加载中…' : '选择 LLM provider（仅显示已配置 key 的）'}
                className="border border-slate-300 rounded px-1.5 py-0.5 text-xs max-w-[140px] focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                {providers.length === 0 && !providersLoading && (
                  <option value="">（无可用 provider）</option>
                )}
                {providers.map((p) => {
                  // R8.2 + R9 阶段 3 (审计员 #3): verified 字段差异化 UI
                  // 之前 verified 字段 (后端 R8 加的) 在前端 types 声明但 UI 不消费,
                  // 配错 key 的 provider 跟没配 key 一样默默从下拉消失 (其实 has_key
                  // 仍然 true, 它会出现在下拉但调用 401, 用户以为是网络问题重试).
                  // 修复 — 三态 UI:
                  //   - verified === false: 🔴 红字 "(key 失效)" + tooltip 提示
                  //     .env/key 问题, 仍可下拉看到, 让用户知道哪个 provider 出问题
                  //   - verified === null: ⏳ 灰色 "(验证中...)" + disabled,
                  //     启动后 5s 内后端 health check 未完成, 强制用户等
                  //   - verified === true: 正常显示, verified 字段不外露
                  //
                  // R10 (M-16): minimax 加 "🎯 默认" 标签 — 让用户一眼知道哪个是默认.
                  if (p.verified === false) {
                    return (
                      <option
                        key={p.id}
                        value={p.id}
                        disabled={false}
                        title="API key 验证失败,请检查 .env 或重新生成"
                        style={{ color: '#dc2626' }}
                      >
                        🔴 {p.name} (key 失效)
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
                        style={{ color: '#94a3b8' }}
                      >
                        ⏳ {p.name} (验证中...)
                      </option>
                    );
                  }
                  // R10 (M-16): minimax 在 option label 上加 "🎯 默认" 标识
                  const isDefault = p.id === 'minimax';
                  return (
                    <option
                      key={p.id}
                      value={p.id}
                      title={p.flagship_model}
                      style={isDefault ? { color: '#1d4ed8', fontWeight: 600 } : undefined}
                    >
                      {isDefault ? `🎯 ${p.name} (默认)` : p.name}
                    </option>
                  );
                })}
              </select>
            </label>
            <label className="flex items-center gap-1 text-slate-600">
              预算
              <input
                type="number"
                min={0.1}
                max={20}
                step={0.1}
                value={budget}
                onChange={(e) => setBudget(parseFloat(e.target.value) || 2.0)}
                className="w-14 border border-slate-300 rounded px-1.5 py-0.5 text-center"
              />
            </label>
            <label className="flex items-center gap-1 text-slate-600">
              迭代
              <input
                type="number"
                min={1}
                max={5}
                value={maxIter}
                onChange={(e) => setMaxIter(parseInt(e.target.value) || 3)}
                className="w-12 border border-slate-300 rounded px-1.5 py-0.5 text-center"
              />
            </label>
          </div>

          <div className="flex items-center gap-2 text-xs">
            {/* Round 6 S1: loading 时 search 按钮变取消按钮, 闭环 Round 5 S-5 后端 cancel.
                之前 loading 期间用户无法中断 8 节点流水线 (SSE + LLM 调用可能跑 30s+),
                按钮文案 '搜索中…' 误导用户以为在排队, 实际无取消能力.
                现在 loading 时:
                  - 按钮文案 '搜索中…' → '取消'
                  - 颜色 brand-600 → rose-600 (语义化危险动作)
                  - 行为 onClick(onReset) → 触发 useSearch.reset → POST /api/v1/search/cancel
                注意 type='button' (不是 'submit'), 避免点取消时误触发表单 submit.
                Round 6 S4': 加 title/aria-label 中文 hover 提示 + 加载中文文案统一化. */}
            {loading ? (
              <button
                type="button"
                onClick={onReset}
                aria-label="取消当前搜索"
                title="点击中断当前检索流水线"
                className="flex-1 bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium py-1.5 rounded-md transition"
              >
                取消
              </button>
            ) : (
              <button
                type="submit"
                disabled={!query.trim()}
                aria-label="开始搜索"
                title={!query.trim() ? '请先输入研究问题' : '开始检索'}
                className="flex-1 bg-brand-600 hover:bg-brand-700 disabled:bg-slate-300 text-white text-sm font-medium py-1.5 rounded-md transition"
              >
                搜索
              </button>
            )}
            <button
              type="button"
              onClick={handleReset}
              disabled={loading}
              className="px-2.5 py-1.5 text-sm border border-slate-300 rounded-md hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
              title={loading ? '请先取消当前搜索' : '清空表单'}
            >
              清空
            </button>
          </div>
        </form>

        {/* Round 6 S4': 加载进度条加中文 aria-label, 屏幕阅读器友好. */}
        {loading && (
          <div
            className="mt-2 p-2 bg-brand-50 border border-brand-200 rounded-md"
            role="status"
            aria-live="polite"
            aria-label="搜索进行中"
          >
            <div className="flex items-center justify-between text-[10px] text-brand-700 mb-1.5">
              <span className="font-medium">
                {pipelineSteps[currentStep]?.emoji} {pipelineSteps[currentStep]?.label}
              </span>
              <span className="font-mono">{elapsedSec.toFixed(1)}s</span>
            </div>
            <div className="grid grid-cols-4 gap-0.5">
              {pipelineSteps.map((s, i) => (
                <div
                  key={s.key}
                  className={`h-1 rounded ${
                    i < currentStep
                      ? 'bg-brand-500'
                      : i === currentStep
                      ? 'bg-brand-300 animate-pulse'
                      : 'bg-slate-200'
                  }`}
                />
              ))}
            </div>
          </div>
        )}

        <div className="mt-2">
          <p className="text-[10px] uppercase text-themed-muted mb-1">示例</p>
          <div className="flex flex-wrap gap-1">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => useSuggestion(s)}
                className="text-[10px] px-1.5 py-0.5 bg-slate-100 hover:bg-slate-200 rounded text-slate-700"
                title={s}
              >
                {s.length > 22 ? s.slice(0, 22) + '…' : s}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {/* Round 5 SIMPLIFY (API-001): 切到 M-1 顶层字段
            is_degraded_response / fallback_paper_count 直接来自后端 SearchResponse
            (Round 5 M-1, commit 0754fa1), 替代之前从 papers[].is_fallback 单篇聚合的 useMemo 派生.
            闭环后端 API + 减 1 个 useMemo. */}
        {isDegradedResponse && (
          <div
            className="bg-amber-50 border-l-4 border-amber-400 text-amber-800 px-4 py-3 mx-3 mt-3 rounded-md flex items-start gap-3"
            role="alert"
            data-testid="degraded-banner"
          >
            <span className="text-amber-600 text-xl leading-none" role="img" aria-label="warning">⚠️</span>
            <div className="flex-1">
              <h4 className="font-semibold text-sm">部分结果来自后备数据</h4>
              <p className="text-xs mt-1 text-amber-700">
                本次搜索触发了 {fallbackPaperCount} 篇论文的后备 fallback
                （可能因 LLM API 限流、key 失效或网络问题）。建议检查 provider 配置后重试。
              </p>
              {/* R10.5 Fix-Diagnose: 自动检测常见 fallback 原因, 给用户可执行的修复建议.
                  旧版只说"可能因限流/key/网络" 太空泛, 用户不知道具体哪里出问题.
                  前端基于 providers 列表 + URL 反向检测给出 actionable hints. */}
              <details className="mt-2 text-xs">
                <summary className="cursor-pointer text-amber-700 hover:text-amber-900 select-none">
                  查看诊断与修复建议
                </summary>
                <ul className="mt-1.5 space-y-1 pl-3 list-disc text-amber-700">
                  {/* 检查 SS key: providers 列表里没有 semantic_scholar 直接标识,
                      但 query 后端能识别. 简易检测: 如果 fallback_paper_count >= 10,
                      强烈怀疑 SS rate-limit (免费 tier 5req/5min). */}
                  {fallbackPaperCount >= 10 && (
                    <li>
                      <strong>Semantic Scholar 限流可能性高</strong>:
                      无 SS API key 时免费配额 100 req/5min, 单次 max_iter=3 × 5 子查询 = 15+ 请求.
                      修复: 在 <code className="bg-amber-100 px-1 rounded">.env</code> 设{' '}
                      <code className="bg-amber-100 px-1 rounded">SEMANTIC_SCHOLAR_API_KEY=xxx</code>{' '}
                      (申请: semanticscholar.org/product/api).
                    </li>
                  )}
                  {/* LLM 失败: 总是显示, 因为 fallback 可能只是部分论文.
                      模板报告 "当前为 mock 模式" 文本已被替换为更明确的提示. */}
                  <li>
                    <strong>LLM 失败降级</strong>:
                    synthesis 节点 fallback 会让综述内容质量降低 (评分统一为 4.0 左右).
                    可尝试: 1) 换 provider (kimi/glm 备选); 2) 降低 max_iterations 减少 LLM 调用次数.
                  </li>
                  <li>
                    <strong>网络/代理</strong>:
                    确认 <code className="bg-amber-100 px-1 rounded">get_proxy()</code> 探测到的代理可达
                    (国内常见端口 7890/7897), SS/OpenAlex 走不通也会触发 fallback.
                  </li>
                </ul>
              </details>
            </div>
          </div>
        )}
        <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-100 sticky top-0 flex items-center justify-between">
          <h3 className="text-xs font-semibold text-slate-600">
            论文列表 {papers.length > 0 && `(${papers.length})`}
          </h3>
          {papers.length > 0 && (
            <span className="text-[10px] text-themed-muted">按相关性排序 · 点击打开</span>
          )}
        </div>
        {lastQuery && papers.length === 0 && (
          <p className="text-xs text-themed-muted p-4 text-center">未找到论文</p>
        )}
        <ul className="divide-y divide-slate-100">
          {papers.map((p, i) => (
            <li
              key={p.paper_id || i}
              className="px-3 py-1.5 hover:bg-slate-50 cursor-pointer transition"
              onClick={() => {
                // BUG-003 / VULN-004 修复：URL 协议白名单 + noopener/noreferrer
                if (p.url && /^https?:\/\//i.test(p.url)) {
                  window.open(p.url, '_blank', 'noopener,noreferrer');
                }
              }}
              title={p.title}
            >
              <div className="flex items-start gap-2">
                <span className="text-[10px] font-mono text-themed-muted mt-0.5 shrink-0 w-5 text-right">
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-1.5">
                    <p className="text-[11px] font-medium text-slate-800 line-clamp-2 leading-tight flex-1">
                      {p.title}
                    </p>
                    {/* P0-2 修复：单篇论文来自 fallback 时，title 旁加醒目标记 */}
                    {p.is_fallback && (
                      <span
                        className="shrink-0 inline-block bg-amber-100 text-amber-700 text-[9px] px-1.5 py-0.5 rounded font-medium"
                        title="此论文来自后备 fallback 数据（非真实 API 检索）"
                        data-testid="paper-fallback-badge"
                      >
                        后备
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5 text-[10px] text-themed-muted">
                    <span>{p.year || '—'}</span>
                    <span>·</span>
                    <span>{p.citation_count.toLocaleString()}</span>
                    <span className="font-mono text-brand-600 font-semibold">
                      ★{p.final_score.toFixed(1)}
                    </span>
                    {p.is_expanded && (
                      <span className="ml-auto text-[9px] bg-amber-100 text-amber-700 px-1 rounded">
                        ext
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
