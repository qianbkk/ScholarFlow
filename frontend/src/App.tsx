import { useCallback, useEffect, useState } from 'react';
import { CostDashboard } from './components/CostDashboard';
import { QueryPanel } from './components/QueryPanel';
import { ReportPanel } from './components/ReportPanel';
import { GraphPanel } from './components/GraphPanel';
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

export default function App() {
  const {
    loading, error, result, lastQuery, search, reset,
    currentStep, elapsedSec, pipelineSteps,
  } = useSearch();
  const [serverOk, setServerOk] = useState<boolean | null>(null);
  const [elapsed, setElapsed] = useState(0);
  // Round 6 SIMPLIFY (REDUNDANT-004): 跟踪上一次成功提交的搜索参数, 给 onRetry 用
  const [lastSearchOpts, setLastSearchOpts] = useState<LastSearchOpts | null>(null);

  useEffect(() => {
    healthCheck()
      .then((d) => setServerOk(d.status === 'ok'))
      .catch(() => setServerOk(false));
  }, []);

  // 当 result 更新时，把后端返回的 elapsed 同步进来
  useEffect(() => {
    if (result?.elapsed_seconds) setElapsed(result.elapsed_seconds);
  }, [result]);

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
