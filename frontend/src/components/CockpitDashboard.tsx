/**
 * Phase 1: 态势感知驾驶舱 (Cockpit Dashboard)
 * 展示 LangGraph 8 节点的实时运行状态，带成本边缘感知光效
 */
import { useEffect, useState, useMemo } from 'react';

// 节点元数据 (与后端 NODE_METADATA 对应)
const NODE_META: Record<string, { display_name: string; model_tier: string; description: string }> = {
  query_decompose: { display_name: '查询分解', model_tier: 'flagship', description: '将用户查询拆解为结构化子问题' },
  search: { display_name: '双源检索', model_tier: 'lightweight', description: '从 Semantic Scholar + OpenAlex 并行检索' },
  expand_citations: { display_name: '引文扩展', model_tier: 'balanced', description: '基于种子论文扩展引用网络' },
  rank: { display_name: '三维排序', model_tier: 'lightweight', description: '权威性/相关性/一致性三维打分' },
  refine: { display_name: '查询优化', model_tier: 'flagship', description: '基于上一轮结果优化查询策略' },
  synthesize: { display_name: '综述生成', model_tier: 'flagship', description: '编织结构化文献综述报告' },
  build_graph: { display_name: '图谱构建', model_tier: 'lightweight', description: '构建 D3 力导向引用图谱' },
  track_cost: { display_name: '成本追踪', model_tier: 'lightweight', description: '汇总 Token 用量与成本' },
};

// 模型等级对应的颜色 (成本边缘感知)
const TIER_COLORS: Record<string, string> = {
  flagship: '#f97316',    // 橙色 - 高成本旗舰模型
  balanced: '#eab308',    // 黄色 - 中等成本平衡模型
  lightweight: '#22c55e', // 绿色 - 低成本轻量模型
};

interface NodeEvent {
  node: string;
  step: number;
  status: 'running' | 'completed';
  model?: string;
  cost_usd?: number;
  tokens?: number;
  elapsed: number;
}

interface Props {
  events: NodeEvent[];
  isRunning: boolean;
  expandedNodeId: string | null;
  onExpandNode: (nodeId: string | null) => void;
}

export function CockpitDashboard({ events, isRunning, expandedNodeId, onExpandNode }: Props) {
  // 计算每个节点的最新状态
  const nodeStates = useMemo(() => {
    const states: Record<string, NodeEvent & { completed: boolean }> = {};
    
    for (const event of events) {
      const prev = states[event.node];
      if (!prev || event.step >= (prev.step ?? -1)) {
        states[event.node] = {
          ...event,
          completed: event.status === 'completed',
        };
      }
    }
    
    return states;
  }, [events]);

  // 当前正在运行的节点
  const runningNode = useMemo(() => {
    for (const nodeKey of Object.keys(NODE_META)) {
      const state = nodeStates[nodeKey];
      if (state && state.status === 'running' && !state.completed) {
        return nodeKey;
      }
    }
    return null;
  }, [nodeStates]);

  // 累计成本
  const totalCost = useMemo(() => {
    let cost = 0;
    for (const state of Object.values(nodeStates)) {
      if (state.cost_usd) {
        cost = Math.max(cost, state.cost_usd);
      }
    }
    return cost;
  }, [nodeStates]);

  // 总 Token 数
  const totalTokens = useMemo(() => {
    let tokens = 0;
    for (const state of Object.values(nodeStates)) {
      if (state.tokens) {
        tokens = Math.max(tokens, state.tokens);
      }
    }
    return tokens;
  }, [nodeStates]);

  return (
    <div className="cockpit-dashboard" style={{
      backgroundColor: 'var(--sf-bg-elev)',
      borderBottom: '1px solid var(--sf-border)',
      padding: '12px 16px',
    }}>
      {/* 顶部摘要栏 */}
      <div className="dashboard-summary" style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '12px',
      }}>
        <div className="summary-left" style={{ display: 'flex', gap: '24px' }}>
          <span className="summary-item" style={{
            fontSize: '12px',
            color: 'var(--sf-muted)',
          }}>
            状态：{isRunning ? (
              <span style={{ color: TIER_COLORS.flagship }}>
                <span className="animate-pulse">●</span> 运行中
              </span>
            ) : (
              <span style={{ color: 'var(--sf-text)' }}>完成</span>
            )}
          </span>
          <span className="summary-item" style={{ fontSize: '12px', color: 'var(--sf-muted)' }}>
            累计成本：<span style={{ color: 'var(--sf-accent)', fontFamily: 'monospace' }}>${totalCost.toFixed(4)}</span>
          </span>
          <span className="summary-item" style={{ fontSize: '12px', color: 'var(--sf-muted)' }}>
            Token: <span style={{ fontFamily: 'monospace' }}>{totalTokens.toLocaleString()}</span>
          </span>
        </div>
        <div className="summary-right" style={{ fontSize: '11px', color: 'var(--sf-muted)' }}>
          LangGraph 态势感知流水线
        </div>
      </div>

      {/* 8 舱室横向流水线 */}
      <div className="node-pipeline" style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(8, 1fr)',
        gap: '8px',
      }}>
        {Object.entries(NODE_META).map(([nodeKey, meta]) => {
          const state = nodeStates[nodeKey];
          const isCurrent = runningNode === nodeKey;
          const isCompleted = state?.completed;
          const tierColor = TIER_COLORS[meta.model_tier] || '#94a3b8';

          return (
            <button
              key={nodeKey}
              onClick={() => onExpandNode(expandedNodeId === nodeKey ? null : nodeKey)}
              className={`node-chamber ${isCurrent ? 'active' : ''} ${isCompleted ? 'completed' : ''}`}
              style={{
                position: 'relative',
                padding: '10px 6px',
                borderRadius: '6px',
                border: `2px solid ${isCurrent ? tierColor : 'var(--sf-border)'}`,
                backgroundColor: isCurrent
                  ? `${tierColor}15`
                  : isCompleted
                  ? 'var(--sf-bg)'
                  : 'transparent',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                minHeight: '70px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {/* 成本边缘光晕 */}
              {isCurrent && (
                <div
                  className="cost-glow"
                  style={{
                    position: 'absolute',
                    inset: '-2px',
                    borderRadius: '6px',
                    boxShadow: `0 0 12px 2px ${tierColor}40`,
                    animation: 'pulse 1.5s ease-in-out infinite',
                    pointerEvents: 'none',
                  }}
                />
              )}

              {/* 节点名称 */}
              <span
                className="node-name"
                style={{
                  fontSize: '11px',
                  fontWeight: isCurrent ? '600' : '500',
                  color: isCurrent ? tierColor : isCompleted ? 'var(--sf-text)' : 'var(--sf-muted)',
                  textAlign: 'center',
                  lineHeight: '1.3',
                }}
              >
                {meta.display_name}
              </span>

              {/* 状态指示器 */}
              {isCurrent && (
                <span
                  className="status-indicator"
                  style={{
                    fontSize: '9px',
                    color: tierColor,
                    marginTop: '4px',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                  }}
                >
                  Running
                </span>
              )}
              {isCompleted && (
                <span
                  className="status-indicator"
                  style={{
                    fontSize: '9px',
                    color: 'var(--sf-accent)',
                    marginTop: '4px',
                  }}
                >
                  ✓
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* 展开的节点详情终端 */}
      {expandedNodeId && nodeStates[expandedNodeId] && (
        <div
          className="node-terminal"
          style={{
            marginTop: '12px',
            padding: '12px',
            backgroundColor: 'var(--sf-bg)',
            borderRadius: '6px',
            border: '1px solid var(--sf-border)',
            fontFamily: 'monospace',
            fontSize: '11px',
          }}
        >
          <div className="terminal-header" style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '8px',
            paddingBottom: '8px',
            borderBottom: '1px solid var(--sf-border)',
          }}>
            <span style={{ color: 'var(--sf-accent)', fontWeight: '600' }}>
              {NODE_META[expandedNodeId]?.display_name} — 思考日志 (Thought Stream)
            </span>
            <button
              onClick={() => onExpandNode(null)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--sf-muted)',
                cursor: 'pointer',
                fontSize: '16px',
              }}
            >
              ×
            </button>
          </div>
          <div className="terminal-content" style={{ color: 'var(--sf-text)' }}>
            {(() => {
              const state = nodeStates[expandedNodeId];
              return (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div><span style={{ color: 'var(--sf-muted)' }}>节点:</span> {expandedNodeId}</div>
                  <div><span style={{ color: 'var(--sf-muted)' }}>步骤:</span> {state?.step ?? 'N/A'}</div>
                  <div><span style={{ color: 'var(--sf-muted)' }}>状态:</span> {state?.status ?? 'unknown'}</div>
                  <div><span style={{ color: 'var(--sf-muted)' }}>耗时:</span> {state?.elapsed.toFixed(2)}s</div>
                  {state?.model && (
                    <div><span style={{ color: 'var(--sf-muted)' }}>模型:</span> {state.model}</div>
                  )}
                  {state?.cost_usd !== undefined && (
                    <div><span style={{ color: 'var(--sf-muted)' }}>成本:</span> ${state.cost_usd.toFixed(4)}</div>
                  )}
                  {state?.tokens !== undefined && (
                    <div><span style={{ color: 'var(--sf-muted)' }}>Token:</span> {state.tokens.toLocaleString()}</div>
                  )}
                  <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px dashed var(--sf-border)' }}>
                    <span style={{ color: 'var(--sf-muted)' }}>描述:</span> {NODE_META[expandedNodeId]?.description}
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
