/**
 * LayoutToggle — 3 列 / 焦点单列 布局切换 (R10.5.40 Agent 1, Phase 2)
 *
 * 从 v4 prototype (newversion/frontend/) 吸收的"阅读优先" 设计:
 *   - 三栏布局 (3-col): 现有 v1 — QueryPanel / ReportPanel / GraphPanel 并排
 *   - 单栏焦点 (focus):  吸收 v4 — GraphPanel 默认收起, 报告区独占中栏
 *     (GraphPanel 不被删, 而是根据 toggle 状态 show/hide; v4 是用 modal
 *      overlay, v1 简化成直接显隐, 因为 GraphPanel 没暴露 ref 切 overlay)
 *
 * 持久化: useLocalStorage('sf-layout-mode'), 默认 'three-col' 跟现有 v1 一致.
 *
 * 为什么不做完整 single-col refactor:
 *   - 任务明确: "Don't actually refactor the entire App.tsx to be a single-column
 *     layout — just make the graph rail show/hide based on the toggle. Keep the
 *     rest of v1's structure intact."
 *   - 所以这里只暴露 showGraph 布尔给父组件, 父组件 (App.tsx) 根据它隐藏 GraphPanel.
 */
import { useLocalStorage } from '../lib/useLocalStorage';
import { STORAGE_KEYS } from '../lib/storageKeys';

export type LayoutMode = 'three-col' | 'focus';

interface Props {
  className?: string;
}

/** Hook 形式 — 父组件 (App.tsx) 调这个拿当前 layoutMode */
export function useLayoutMode(): [LayoutMode, (v: LayoutMode | ((p: LayoutMode) => LayoutMode)) => void] {
  return useLocalStorage<LayoutMode>(STORAGE_KEYS.layoutMode, 'three-col');
}

export function LayoutToggle({ className = '' }: Props) {
  const [mode, setMode] = useLocalStorage<LayoutMode>(STORAGE_KEYS.layoutMode, 'three-col');

  return (
    <button
      type="button"
      onClick={() => setMode((m) => (m === 'three-col' ? 'focus' : 'three-col'))}
      aria-label={mode === 'three-col' ? '切换到单栏焦点布局' : '切换到三栏布局'}
      aria-pressed={mode === 'focus'}
      title={
        mode === 'three-col'
          ? '当前: 三栏布局 (点击收起图谱列, 报告区更宽)'
          : '当前: 单栏焦点 (点击恢复图谱列)'
      }
      data-testid="layout-toggle"
      className={`flex items-center gap-1.5 px-2 py-1 text-[11px] font-mono uppercase tracking-[0.12em] transition-colors ${className}`}
      style={{
        backgroundColor: 'var(--sf-bg)',
        color: 'var(--sf-text)',
        border: '1px solid var(--sf-border)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--sf-accent)';
        e.currentTarget.style.color = 'var(--sf-accent)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--sf-border)';
        e.currentTarget.style.color = 'var(--sf-text)';
      }}
    >
      {/* glyph: 3 竖线 = 三栏, 1 竖线 = 单栏焦点 (极简抽象) */}
      <span aria-hidden="true" className="inline-flex items-center gap-[2px] shrink-0">
        {mode === 'three-col' ? (
          <>
            <span style={{ display: 'inline-block', width: 2, height: 8, backgroundColor: 'currentColor' }} />
            <span style={{ display: 'inline-block', width: 2, height: 8, backgroundColor: 'currentColor' }} />
            <span style={{ display: 'inline-block', width: 2, height: 8, backgroundColor: 'currentColor' }} />
          </>
        ) : (
          <span style={{ display: 'inline-block', width: 2, height: 10, backgroundColor: 'currentColor' }} />
        )}
      </span>
      <span className="font-medium">{mode === 'three-col' ? '三栏' : '单栏'}</span>
    </button>
  );
}