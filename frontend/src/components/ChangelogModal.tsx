/**
 * ChangelogModal — R10.5.59 release notes
 */
import { useStore, actions } from '../store/useStore';

const ENTRIES = [
  {
    version: 'R10.5.59',
    date: '2026-06-21',
    summary: '5 项迭代:hamburger Settings / paper_count 滑块 / LLM strict ≥ 8 → 7 / 搜索概要 + 报告居中 / 图谱 jitter 修复 / 完整 i18n',
    items: [
      'TopNav: ⚙ 齿轮按钮删除,改用左侧 ☰ 三横线按钮唤起 SettingsDrawer;删除 settings tab',
      'SettingsDrawer: 删 "midnight 主题天然是夜间模式" 文案;仅留 4 主题色块',
      'QueryInput: 加 paperMin/paperMax 双滑块 (3-30, 默认 5-10),与 budget/iter 并排',
      '后端 LLM 模式 strict ≥ 8 分 (真实有效文献门槛) → 不够自动放宽到 ≥ 7 → 再不够宁可降低数量绝不 mock fallback',
      'Search 视图新增 SearchSummary 概要卡 (报告标题 + Top 5 + 跳报告按钮);不再渲染完整报告',
      'Report 视图内容居中 (maxWidth 720),加 "← 回到 Search" 跳回按钮',
      'GraphPage: 修复 hover 颤动 bug — 主 D3 effect 移除 hovered deps,改用 hoveredRef,鼠标滑动节点位置稳定不再颤动;删除 "§ 4" 章节前缀',
      '完整 i18n 覆盖 (~180 key):TopNav / Search / Report / Graph / History / Settings / Auth / CommandPalette / PipelineProgress 全部中英双语切换',
      '清理 3 个死文件:frontend/src/hooks/useSearch.ts + useLocalStorage.ts + paperFilters.ts (BACKLOG D-005)',
      'README + ROADMAP + BACKLOG + ChangelogModal + VERSION 同步到 R10.5.59',
    ],
  },
  {
    version: 'R10.5.55',
    date: '2026-06-21',
    summary: 'i18n 中英文切换 + D3 图谱独立 tab + SettingsDrawer + Auth 严格化',
    items: [
      '新建 i18n/index.ts (中英字典 + useT hook) + TopNav 中/EN 切换按钮',
      'GraphPage 完整复刻旧 GraphPanel 18 项特性 (filter / 2-hop / 全屏 / drag-to-fix / 富 tooltip / 社区颜色 / 双击打开) 作为独立 Graph tab',
      'SettingsView 替换为 SettingsDrawer (左侧滑出, 4 主题 + runtime mode + API key + 键盘 + 关于 6 分组);删 isDark 独立暗黑模式',
      'runtimeMode 改名 ' + "'" + 'mock/real' + "'" + ' → ' + "'" + 'local/llm' + "'" + ';LLM 检索模式不允许 mock fallback',
      'AuthDialog 拆 register/login 双 tab,8 类错误信息区分;新增 ' + "'" + '/auth/revoke' + "'" + ' 自助轮换 key;logout 真正调后端',
      '后端 7 agent 加 _step() thinking log 调用 + SSE 流式 emit + 前端 PipelineProgress 逐条 fade-in',
    ],
  },
  {
    version: 'R10.5.54',
    date: '2026-06-20',
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