/**
 * ChangelogModal — R10.5.54 release notes
 */
import { useStore, actions } from '../store/useStore';

const ENTRIES = [
  {
    version: 'R10.5.54',
    date: '2026-06-21',
    summary: 'Frontend complete rebuild — Editorial Desk Reference visual language',
    items: [
      '新建 tokens.ts (OKLCH 主题) + useStore (单 store 取代 3 Contexts + 13 useState)',
      'TopNav / SearchWorkspace / QueryInput / PaperList / PipelineProgress / ReportView 12 组件',
      '8 节点流水线 + 节点级 thinking log + build_graph 图谱演化 scrubber 合并到 PipelineProgress',
      'CockpitDashboard / CostDashboard / EvolutionSlider / PipelineStrip / HistoryPanel / SettingsPanel / ReportPanel / GraphPanel / QueryPanel 等 15 文件进入移除清单',
    ],
  },
  {
    version: 'R10.5.53',
    date: '2026-06-20',
    summary: '前代 4-tab 重构 + 图谱演化折叠进流水线',
    items: [
      '4-tab routing (Search / Report / History / Settings)',
      '删 R10.5.28 升级公告 banner',
      '节点级思考日志 (query_decompose / query_refiner)',
    ],
  },
];

export function ChangelogModal() {
  const open = useStore((s) => s.changelogOpen);
  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Changelog"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.4)',
      }}
      onClick={actions.closeChangelog}
    >
      <div
        className="sf-fade-in"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 480,
          maxWidth: 'calc(100vw - 48px)',
          maxHeight: '70vh',
          overflowY: 'auto',
          backgroundColor: 'var(--sf-bg)',
          border: '1px solid var(--sf-border)',
          borderRadius: 4,
          padding: 32,
        }}
      >
        <header
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            marginBottom: 16,
            paddingBottom: 12,
            borderBottom: '1px solid var(--sf-border)',
          }}
        >
          <h1 className="font-display" style={{ fontSize: 24, letterSpacing: '-0.02em', margin: 0 }}>
            Changelog
          </h1>
          <button
            type="button"
            onClick={actions.closeChangelog}
            className="sf-btn font-ui"
            style={{ padding: '4px 10px', fontSize: 12 }}
          >
            ✕
          </button>
        </header>

        <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {ENTRIES.map((e, i) => (
            <li
              key={e.version}
              style={{
                padding: '16px 0',
                borderTop: i > 0 ? '1px solid var(--sf-border)' : 'none',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 12,
                  marginBottom: 8,
                }}
              >
                <span
                  className="font-mono"
                  style={{ fontSize: 13, fontWeight: 600, color: 'var(--sf-accent)' }}
                >
                  {e.version}
                </span>
                <span className="font-mono" style={{ fontSize: 11, color: 'var(--sf-muted)' }}>
                  {e.date}
                </span>
              </div>
              <p className="font-body" style={{ fontSize: 14, margin: '0 0 8px' }}>
                {e.summary}
              </p>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {e.items.map((it, j) => (
                  <li
                    key={j}
                    className="font-body"
                    style={{ fontSize: 13, color: 'var(--sf-text)', marginBottom: 4 }}
                  >
                    {it}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}