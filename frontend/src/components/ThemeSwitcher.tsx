/**
 * ThemeSwitcher — 4 套 Editorial 主题切换 (R10.5.4)
 *
 * 主题 (CSS 变量驱动, 全部 WCAG AA, 见 index.css):
 *   parchment (默认)  📜 暖米羊皮纸 · ink 文字 · burnt orange 强调
 *   kraft             🪵 牛皮纸     · ink 文字 · terracotta 强调
 *   midnight          🌑 深墨水     · cream 文字 · bright orange 强调
 *   sage              🌿 sage 纸    · ink 文字 · rust 强调
 *
 * UI: 极简 — 一个圆形色卡 (点开是 4 个色卡 + 名称), 模仿杂志"印刷工艺选择" 风格.
 */
import { useState } from 'react';

export type ThemeId = 'parchment' | 'kraft' | 'midnight' | 'sage';

export const THEME_META: Record<
  ThemeId,
  { label: string; emoji: string; desc: string; bg: string; text: string; contrast: string }
> = {
  parchment: {
    label: '羊皮纸',
    emoji: '📜',
    desc: '默认 — 暖米色 + 燃烧橙',
    bg: '#faf6ed',
    text: '#1c1917',
    contrast: '14.8:1',
  },
  kraft: {
    label: '牛皮纸',
    emoji: '🪵',
    desc: '暖阅读 — kraft + terracotta',
    bg: '#f4ecd8',
    text: '#1c1917',
    contrast: '11.2:1',
  },
  midnight: {
    label: '深墨水',
    emoji: '🌑',
    desc: '夜间 — 深黑 + cream + 亮橙',
    bg: '#0d0d0d',
    text: '#f5efe4',
    contrast: '15.1:1',
  },
  sage: {
    label: 'Sage',
    emoji: '🌿',
    desc: '护眼 — sage 纸 + rust 强调',
    bg: '#e8e4d4',
    text: '#1c1917',
    contrast: '9.4:1',
  },
};

interface Props {
  current: ThemeId;
  onChange: (theme: ThemeId) => void;
}

export function ThemeSwitcher({ current, onChange }: Props) {
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
        className="flex items-center gap-1.5 px-2 py-1 text-[11px] font-mono uppercase tracking-[0.12em] transition-colors"
        style={{
          backgroundColor: 'var(--sf-bg)',
          color: 'var(--sf-text)',
          border: '1px solid var(--sf-border)',
        }}
      >
        <span
          className="inline-block w-3 h-3 rounded-full shrink-0"
          style={{ backgroundColor: meta.bg, border: '1px solid var(--sf-border)' }}
          aria-hidden="true"
        />
        <span className="font-medium">{meta.label}</span>
        <span className="text-[9px] opacity-60">▾</span>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div
            className="absolute right-0 mt-1 z-20 min-w-[260px] overflow-hidden font-ui"
            style={{
              backgroundColor: 'var(--sf-bg-elev)',
              border: '1px solid var(--sf-border)',
              boxShadow: 'var(--sf-shadow)',
            }}
            role="menu"
          >
            <div
              className="px-3 py-2 text-[9px] font-mono uppercase tracking-[0.18em] border-b"
              style={{
                color: 'var(--sf-muted)',
                borderColor: 'var(--sf-border)',
              }}
            >
              印刷工艺选择
            </div>
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
                  className="flex items-center gap-2.5 w-full px-3 py-2 text-xs text-left transition-colors"
                  style={{
                    color: 'var(--sf-text)',
                    backgroundColor: isActive ? 'var(--sf-bg)' : 'transparent',
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.backgroundColor = 'var(--sf-bg)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = isActive
                      ? 'var(--sf-bg)'
                      : 'transparent';
                  }}
                >
                  <span
                    className="w-5 h-5 rounded-sm shrink-0 flex items-center justify-center text-[10px]"
                    style={{
                      backgroundColor: m.bg,
                      color: m.text,
                      border: '1px solid var(--sf-border)',
                    }}
                    aria-hidden="true"
                  >
                    {m.emoji}
                  </span>
                  <span className="flex-1 min-w-0">
                    <span
                      className="font-display italic font-semibold text-[13px]"
                      style={{ color: 'var(--sf-text)' }}
                    >
                      {m.label}
                    </span>
                    <span
                      className="text-[10px] ml-1.5"
                      style={{ color: 'var(--sf-muted)' }}
                    >
                      {m.desc}
                    </span>
                  </span>
                  <span
                    className="text-[9px] font-mono tabular-nums shrink-0"
                    style={{ color: 'var(--sf-muted)' }}
                  >
                    {m.contrast}
                  </span>
                  {isActive && (
                    <span
                      className="text-xs shrink-0"
                      style={{ color: 'var(--sf-accent)' }}
                      aria-label="当前"
                    >
                      ●
                    </span>
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
