/**
 * PipelineProgress — R10.5.59 取代 CockpitDashboard + EvolutionSlider + PipelineStrip + CostDashboard
 *
 * 单行 8 tick (● ○ ●) + 行右端 cost/elapsed/tokens.
 * 展开节点显示 thinking 日志; build_graph 节点专属显示 graph evolution scrubber.
 */
import { useState, useEffect } from 'react';
import { useStore, actions } from '../store/useStore';
import { useT } from '../i18n';

const NODES = [
  { key: 'query_decompose' },
  { key: 'search' },
  { key: 'expand_citations' },
  { key: 'rank' },
  { key: 'refine' },
  { key: 'synthesize' },
  { key: 'build_graph' },
  { key: 'track_cost' },
] as const;

export function PipelineProgress() {
  const events = useStore((s) => s.events);
  const nodeThinking = useStore((s) => s.nodeThinking);
  const graphSnapshots = useStore((s) => s.graphSnapshots);
  const expandedNodeId = useStore((s) => s.expandedNodeId);
  const loading = useStore((s) => s.loading);
  const elapsed = useStore((s) => s.elapsed);
  const result = useStore((s) => s.result);
  const t = useT();

  const nodeState: Record<string, { status: 'idle' | 'running' | 'done' | 'error'; step?: number; cost?: number; tokens?: number; elapsed?: number }> = {};
  for (const n of NODES) nodeState[n.key] = { status: 'idle' };
  for (const ev of events) {
    nodeState[ev.node] = {
      status: ev.status === 'completed' ? 'done' : 'running',
      step: ev.step,
      cost: ev.cost_usd,
      tokens: ev.tokens,
      elapsed: ev.elapsed,
    };
  }
  const lastIdx = events.length;
  if (loading && lastIdx < NODES.length && nodeState[NODES[lastIdx].key].status === 'idle') {
    nodeState[NODES[lastIdx].key] = { status: 'running' };
  }

  let totalCost = 0;
  let totalTokens = 0;
  for (const s of Object.values(nodeState)) {
    if (s.cost && s.cost > totalCost) totalCost = s.cost;
    if (s.tokens && s.tokens > totalTokens) totalTokens = s.tokens;
  }
  const displayElapsed = (result?.elapsed_seconds as number | undefined) ?? elapsed;

  const [evolutionIdx, setEvolutionIdx] = useState(0);
  useEffect(() => {
    if (graphSnapshots.length > 0) setEvolutionIdx(graphSnapshots.length - 1);
  }, [graphSnapshots.length]);
  const currentSnap = graphSnapshots[evolutionIdx];

  return (
    <section
      style={{
        padding: '12px 0',
        borderTop: '1px solid var(--sf-border)',
        borderBottom: '1px solid var(--sf-border)',
      }}
    >
      {/* 8 ticks row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        {NODES.map((n) => {
          const s = nodeState[n.key];
          const isRunning = s.status === 'running';
          const isDone = s.status === 'done';
          const expanded = expandedNodeId === n.key;
          const label = t(`pipeline.node.${n.key}`);
          return (
            <button
              key={n.key}
              type="button"
              onClick={() => actions.toggleNodeExpand(expanded ? null : n.key)}
              aria-expanded={expanded}
              aria-label={`${label} · ${s.status}`}
              data-testid={`pipeline-${n.key}`}
              className="font-ui"
              style={{
                background: 'none',
                border: 'none',
                padding: '4px 6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                color: isDone ? 'var(--sf-text)' : isRunning ? 'var(--sf-accent)' : 'var(--sf-muted)',
                fontSize: 12,
                fontWeight: isDone ? 600 : 400,
              }}
            >
              <span
                aria-hidden
                style={{
                  display: 'inline-block',
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  border: isDone ? 'none' : '1px solid currentColor',
                  backgroundColor: isDone
                    ? 'var(--sf-accent)'
                    : 'transparent',
                  flexShrink: 0,
                }}
                className={isRunning ? 'sf-pulse' : ''}
              />
              <span>{label}</span>
            </button>
          );
        })}

        <div style={{ flex: 1 }} />

        <span
          className="font-mono"
          style={{ fontSize: 11, color: 'var(--sf-muted)' }}
        >
          {displayElapsed.toFixed(1)}s · ${totalCost.toFixed(4)} · {totalTokens.toLocaleString()} tok
        </span>
      </div>

      {/* Expanded node detail */}
      {expandedNodeId && (
        <div
          className="sf-fade-in"
          style={{
            marginTop: 12,
            padding: '12px 0',
            borderTop: '1px dashed var(--sf-border)',
          }}
        >
          <div
            className="font-ui"
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--sf-text)',
              marginBottom: 8,
            }}
          >
            {t(`pipeline.node.${expandedNodeId}`)} · {t('pipeline.thinkingTitle')}
          </div>
          {nodeThinking[expandedNodeId] && nodeThinking[expandedNodeId].length > 0 ? (
            <ol
              className="font-mono"
              style={{
                listStyle: 'decimal',
                paddingLeft: 20,
                margin: 0,
                fontSize: 11,
                lineHeight: 1.5,
                color: 'var(--sf-text)',
                maxHeight: 200,
                overflowY: 'auto',
              }}
            >
              {nodeThinking[expandedNodeId].map((m, i) => (
                <li
                  key={`${expandedNodeId}-${i}`}
                  className="sf-fade-in"
                  style={{ marginBottom: 4 }}
                >
                  {m}
                </li>
              ))}
            </ol>
          ) : (
            <p
              className="font-body"
              style={{
                fontSize: 12,
                color: 'var(--sf-muted)',
                fontStyle: 'italic',
                margin: 0,
              }}
            >
              {t('pipeline.thinkingEmpty')}
            </p>
          )}

          {/* build_graph 专属: graph evolution scrubber */}
          {expandedNodeId === 'build_graph' && graphSnapshots.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 4,
                }}
              >
                <span className="font-ui" style={{ fontSize: 12, fontWeight: 600 }}>
                  {t('pipeline.evolution')}
                </span>
                {currentSnap && (
                  <span className="font-mono" style={{ fontSize: 11, color: 'var(--sf-muted)' }}>
                    {t('pipeline.evolutionSnap', { iter: currentSnap.iteration, n: currentSnap.node_count, l: currentSnap.link_count })}
                  </span>
                )}
              </div>
              <input
                type="range"
                min={0}
                max={Math.max(0, graphSnapshots.length - 1)}
                value={evolutionIdx}
                onChange={(e) => setEvolutionIdx(parseInt(e.target.value, 10))}
                disabled={graphSnapshots.length <= 1}
                style={{ width: '100%', accentColor: 'var(--sf-accent)' }}
                aria-label={t('pipeline.evolution')}
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
}