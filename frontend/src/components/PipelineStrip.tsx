/**
 * PipelineStrip — 8 节点流水线状态条 (R10.5.40 Agent 1, Phase 2)
 *
 * 从 R10.5.38 prototype (R10.5.52 已删) 吸收的设计:
 *   - 横向一行, 8 个节点, 单色 mono 小字
 *   - 每个节点有状态指示 (pending / running / done / error)
 *   - 放在 QueryPanel 顶部 (查询输入框上方), 1 行, hairline bottom border, 不是 card
 *
 * 数据源:
 *   - v1 后端 SSE (/api/v1/search/stream) 推送事件:
 *       'started'         → 清空 + 重置 currentStep
 *       'node_complete'   → 单个节点完成
 *       'done' / 'error'  → 全部完成
 *   - 注意: v1 后端 SSE **目前只发 node_complete 事件** (即"完成" 状态),
 *     没有 "node_start" 事件. 因此 'running' 状态只能从 currentStep 间接推断
 *     (currentStep 指向的节点为 running). 这是 v1 实现的真实约束 — 待 v1 后端
 *     补 node_start 事件后可无缝升级 (只需把 status 字段加上 'started').
 *
 * 当前实现策略:
 *   - status = 'done'    ← 节点已 node_complete (events 里有该 node)
 *   - status = 'running' ← currentStep 指向该节点 (仅在 loading 时)
 *   - status = 'error'   ← search 报 error 时, currentStep 之后的节点
 *   - status = 'pending' ← 其他
 *
 * 设计:
 *   - 1 行, height ~28px, hairline bottom border (Editorial 印刷感)
 *   - mono font, 10px, 大写 + tracking, 跟 CockpitDashboard 不冲突
 *   - 不发请求, 纯接收 props. QueryPanel 拿 useSearch.events + currentStep + loading 喂进来.
 */
import type { NodeEvent } from '../hooks/useSearch';

export type PipelineStatus = 'pending' | 'running' | 'done' | 'error';

// 8 节点定义 — 与 backend LangGraph NODE_NAME_TO_STEP 保持一致 (frontend/src/hooks/useSearch.ts)
// 顺序与 CockpitDashboard NODE_META 一致 (Agent 5 不动此 slice, 名字跟现有常量同步)
const NODES: Array<{ key: string; label: string }> = [
  { key: 'decompose', label: 'decompose' },
  { key: 'refine',    label: 'refine' },
  { key: 'search',    label: 'search' },
  { key: 'score',     label: 'score' },
  { key: 'extract',   label: 'extract' },
  { key: 'gap',       label: 'gap' },
  { key: 'critic',    label: 'critic' },
  { key: 'synthesize', label: 'synthesize' },
];

// 映射 v1 后端 node_complete 事件中的 node name → strip 的 key.
// 注意 v1 useSearch 已用 NODE_NAME_TO_STEP 把 query_decompose→0, search→1 等;
// 这里再次映射是因为 strip 用更短的名字 (8 chars 以内).
function mapNodeNameToStripKey(nodeName: string): string | null {
  const map: Record<string, string> = {
    query_decompose: 'decompose',
    search: 'search',
    expand_citations: 'extract',  // v1 expand_citations ≈ extract (拉 citation 数据)
    rank: 'score',
    refine: 'refine',
    synthesize: 'synthesize',
    build_graph: 'gap',           // v1 build_graph ≈ gap (找知识缺口)
    track_cost: 'critic',         // v1 track_cost ≈ critic (评估/汇总)
  };
  return map[nodeName] ?? null;
}

interface Props {
  /** v1 useSearch.events (NodeEvent[]): 已完成的节点会进 events, 这里用来算 done 状态 */
  events: NodeEvent[];
  /** 当前正在跑 / 已跑到第几步 — v1 用 0-based step index */
  currentStep: number;
  /** 是否正在跑 */
  loading: boolean;
  /** 是否有 error — 有的话 currentStep 之后节点标 error */
  hasError?: boolean;
  className?: string;
}

/** 计算每个节点的当前状态. 公开给 unit test 用. */
export function computeStatuses(
  events: NodeEvent[],
  currentStep: number,
  loading: boolean,
  hasError: boolean,
): PipelineStatus[] {
  // 收集已完成的 strip key
  const doneKeys = new Set<string>();
  for (const ev of events) {
    const k = mapNodeNameToStripKey(ev.node);
    if (k) doneKeys.add(k);
  }

  return NODES.map((n, i) => {
    if (doneKeys.has(n.key)) return 'done';
    if (hasError && i > currentStep) return 'error';
    if (loading && i === currentStep) return 'running';
    if (loading && i < currentStep) {
      // currentStep 之前但 events 里没记录的节点: v1 SSE 偶发漏发,
      // 兜底视为 done (避免显示成 pending, 误导用户以为没在跑)
      return 'done';
    }
    return 'pending';
  });
}

function Glyph({ status }: { status: PipelineStatus }) {
  // R10.5.40 (Agent 1): 极简 glyph, 跟 R10.5.38 prototype Header 一致
  const colorVar = `var(--sf-pipeline-status-${status})`;
  if (status === 'done') return <span style={{ color: colorVar, fontFamily: 'JetBrains Mono, monospace', fontSize: '10px' }}>●</span>;
  if (status === 'running') return <span style={{ color: colorVar, fontFamily: 'JetBrains Mono, monospace', fontSize: '10px', animation: 'sf-fade 1s ease infinite alternate' }}>●</span>;
  if (status === 'error') return <span style={{ color: colorVar, fontFamily: 'JetBrains Mono, monospace', fontSize: '10px' }}>✕</span>;
  return <span style={{ color: colorVar, fontFamily: 'JetBrains Mono, monospace', fontSize: '10px' }}>○</span>;
}

export function PipelineStrip({ events, currentStep, loading, hasError = false, className = '' }: Props) {
  const statuses = computeStatuses(events, currentStep, loading, hasError);

  return (
    <div
      className={`sf-pipeline-strip flex items-center gap-2 px-3 py-1.5 font-mono ${className}`}
      style={{
        // 1 行 hairline bottom border — Editorial 印刷感, 不做 card
        borderBottom: '1px solid var(--sf-border)',
        backgroundColor: 'var(--sf-bg)',
      }}
      role="status"
      aria-live="polite"
      aria-label="8 节点流水线状态"
      data-testid="pipeline-strip"
    >
      {/* 节点组 */}
      <ol className="flex items-center flex-1 m-0 p-0 list-none gap-1.5 min-w-0 overflow-x-auto" style={{ listStyle: 'none' }}>
        {NODES.map((n, i) => (
          <li
            key={n.key}
            className="flex items-center gap-1 shrink-0"
            data-pipeline-node={n.key}
            data-pipeline-status={statuses[i]}
            title={`${i + 1}. ${n.label} — ${statuses[i]}`}
          >
            <Glyph status={statuses[i]} />
            <span
              className="text-[10px] uppercase tracking-[0.12em] whitespace-nowrap"
              style={{
                color:
                  statuses[i] === 'pending' ? 'var(--sf-muted)' : 'var(--sf-text)',
              }}
            >
              {n.label}
            </span>
            {i < NODES.length - 1 && (
              <span
                aria-hidden="true"
                className="inline-block mx-1 shrink-0"
                style={{
                  width: 8,
                  height: 1,
                  backgroundColor:
                    statuses[i] === 'done' ? 'var(--sf-accent)' : 'var(--sf-border)',
                }}
              />
            )}
          </li>
        ))}
      </ol>

      {/* 右侧: 状态文字 (极简, 跟 R10.5.38 prototype Header 一致) */}
      <span
        className="text-[10px] uppercase tracking-[0.18em] shrink-0 tabular-nums"
        style={{
          color: hasError
            ? 'var(--sf-pipeline-status-error)'
            : loading
            ? 'var(--sf-accent)'
            : 'var(--sf-muted)',
        }}
        data-testid="pipeline-strip-status"
      >
        {hasError ? 'ERROR' : loading ? 'RUNNING' : 'IDLE'}
      </span>
    </div>
  );
}