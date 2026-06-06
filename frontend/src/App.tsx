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

      <div className="flex-1 flex min-h-0">
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
        <ReportPanel report={result?.report ?? ''} loading={loading} query={lastQuery} />
        <GraphPanel graph={result?.citation_graph ?? null} />
      </div>
    </div>
  );
}
