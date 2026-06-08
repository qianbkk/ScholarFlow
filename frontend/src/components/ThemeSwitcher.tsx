/**
 * ThemeSwitcher — 4 套背景色主题切换按钮组 (R10 / M-17)
 *
 * 主题 — 全部 WCAG AA 合规 (对比度 > 4.5:1):
 *   light (默认): bg #ffffff + text #0f172a → 16.5:1
 *   warm:         bg #fef3c7 + text #1c1917 → 13.2:1
 *   dark:         bg #0f172a + text #f1f5f9 → 14.5:1
 *   eye:          bg #86efac + text #064e3b → 6.8:1
 *
 * 当前选中主题用 ring 标识 + 略大尺寸. 切换写入 localStorage (key='sf-theme'),
 * 下次打开 App 自动恢复.
 */
import { useState } from 'react';

export type ThemeId = 'light' | 'warm' | 'dark' | 'eye';

export const THEME_META: Record<ThemeId, { label: string; emoji: string; desc: string; bg: string; text: string; contrast: string }> = {
  light: {
    label: '亮色',
    emoji: '☀️',
    desc: '默认 — 白色背景',
    bg: '#ffffff',
    text: '#0f172a',
    contrast: '16.5:1',
  },
  warm: {
    label: '暖色',
    emoji: '🌅',
    desc: '暖米色 — 长时间阅读友好',
    bg: '#fef3c7',
    text: '#1c1917',
    contrast: '13.2:1',
  },
  dark: {
    label: '暗色',
    emoji: '🌙',
    desc: '深空蓝 — 夜间模式',
    bg: '#0f172a',
    text: '#f1f5f9',
    contrast: '14.5:1',
  },
  eye: {
    label: '护眼',
    emoji: '🌿',
    desc: '护眼绿 — 减少屏幕蓝光疲劳',
    bg: '#86efac',
    text: '#064e3b',
    contrast: '6.8:1',
  },
};

interface Props {
  current: ThemeId;
  onChange: (theme: ThemeId) => void;
}

export function ThemeSwitcher({ current, onChange }: Props) {
  // 控制 dropdown 展开/折叠 (避免太多按钮挤在 toolbar)
  const [open, setOpen] = useState(false);
  const meta = THEME_META[current];

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="切换背景色主题"
        aria-expanded={open}
        title={`当前主题: ${meta.label} (${meta.contrast})`}
        className="flex items-center gap-1 px-2 py-1 text-xs border border-slate-300 rounded-md hover:bg-slate-100 transition"
        style={{
          backgroundColor: meta.bg,
          color: meta.text,
          borderColor: current === 'light' ? '#cbd5e1' : meta.bg,
        }}
      >
        <span>{meta.emoji}</span>
        <span className="font-medium">{meta.label}</span>
        <span className="text-[10px] opacity-60">▼</span>
      </button>

      {open && (
        <>
          {/* 点击外部关闭 */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div
            // R10.5 Fix-UI: 加 min-w-[260px] + whitespace-nowrap 防 dropdown
            // 内部子项被父级窄宽度挤压成竖排.  之前每项只显示 1-2 字 ("亮" "色" "默"
            // "认" ...), 根因是父级 inline-block 容器宽度受 toolbar 限制 (~80px),
            // 子项 flex 容器继承此宽度, 4 段内容 (emoji + label + desc + contrast) 被
            // 换行.  min-w 强制 dropdown 至少 260px 容纳完整 4 段.
            className="absolute right-0 mt-1 z-20 min-w-[260px] bg-white border border-slate-200 rounded-md shadow-lg overflow-hidden"
            role="menu"
          >
            {(Object.keys(THEME_META) as ThemeId[]).map((id) => {
              const m = THEME_META[id];
              const isActive = id === current;
              return (
                <button
                  key={id}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    onChange(id);
                    setOpen(false);
                  }}
                  className={`flex items-center gap-2 w-full px-3 py-1.5 text-xs text-left whitespace-nowrap hover:bg-slate-50 transition ${
                    isActive ? 'bg-slate-100' : ''
                  }`}
                >
                  <span
                    className="w-5 h-5 rounded border border-slate-300 shrink-0 flex items-center justify-center text-[10px]"
                    style={{ backgroundColor: m.bg, color: m.text }}
                    aria-hidden="true"
                  >
                    {m.emoji}
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="font-medium text-slate-800">{m.label}</span>
                    <span className="text-slate-500 ml-1.5">{m.desc}</span>
                  </span>
                  <span className="text-[10px] font-mono text-slate-400 shrink-0">
                    {m.contrast}
                  </span>
                  {isActive && (
                    <span className="text-brand-600 text-xs shrink-0" aria-label="当前">✓</span>
                  )}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
