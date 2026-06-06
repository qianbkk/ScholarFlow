import { useEffect, useState } from 'react';
import { CostDashboard } from './components/CostDashboard';
import { QueryPanel } from './components/QueryPanel';
import { ReportPanel } from './components/ReportPanel';
import { GraphPanel } from './components/GraphPanel';
import { useSearch } from './hooks/useSearch';
import { healthCheck } from './services/api';

export default function App() {
  const {
    loading, error, result, lastQuery, search, reset,
    currentStep, elapsedSec, pipelineSteps,
  } = useSearch();
  const [serverOk, setServerOk] = useState<boolean | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    healthCheck()
      .then((d) => setServerOk(d.status === 'ok'))
      .catch(() => setServerOk(false));
  }, []);

  // 当 result 更新时，把后端返回的 elapsed 同步进来
  useEffect(() => {
    if (result?.elapsed_seconds) setElapsed(result.elapsed_seconds);
  }, [result]);

  return (
    <div className="h-screen flex flex-col bg-slate-50">
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
          onSearch={search}
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
            ReportPanel 在 R4 U4 已加 errorMsg/lastQuery/onRetry 三个 optional prop,
            App.tsx 之前未透传, 导致 ReportPanel 的"重试"按钮永远不显示.
            现在从 useSearch 暴露的 error/lastQuery 透传,
            onRetry 直接复用 useSearch.search 闭包, 预算/迭代/provider 走默认参数. */}
        <ReportPanel
          report={result?.report ?? ''}
          loading={loading}
          query={lastQuery}
          errorMsg={error}
          lastQuery={lastQuery}
          onRetry={(q) => search(q)}
        />
        <GraphPanel graph={result?.citation_graph ?? null} />
      </div>
    </div>
  );
}
