/**
 * ThemeToggle — 二元暗黑模式开关 (R10.5.40 Agent 1, Phase 2)
 *
 * 跟现有 4 套 Editorial 主题 (ThemeSwitcher: parchment/kraft/midnight/sage)
 * 正交, 是用户级别的"夜间模式"开关. 开启后, 当前 Editorial 主题被强制渲染
 * 为暗底配色 (CSS 变量在 [data-theme="dark"] 选择器下覆盖).
 *
 * 为什么分两个组件:
 *   - ThemeSwitcher: 学术编辑风格切换 (暖米/牛皮/深墨/sage), 4 选 1
 *   - ThemeToggle: 暗黑/明亮, 2 选 1, 用户使用环境 (白天/晚上) 维度
 * 用户可以同时选 "kraft + dark" (暖色暗底) 或 "parchment + light" (默认).
 *
 * 实现:
 *   - useLocalStorage('sf-dark-mode') 持久化 boolean
 *   - 写入 <html data-theme="dark"|"light"> 由 index.css [data-theme="dark"] 块接管
 *   - 默认 light (跟现有默认 Editorial 主题 parchment 兼容)
 */
import { useLocalStorage } from '../lib/useLocalStorage';
import { STORAGE_KEYS } from '../lib/storageKeys';
import { useEffect } from 'react';

interface Props {
  /** 父组件可选传 className 调位置 */
  className?: string;
}

export function ThemeToggle({ className = '' }: Props) {
  const [dark, setDark] = useLocalStorage<boolean>(STORAGE_KEYS.darkMode, false);

  // 同步 <html data-theme>. 这里用 useEffect 跟随 state 变化;
  // 跨 tab 同步由 useLocalStorage 的 storage 事件监听处理.
  useEffect(() => {
    const html = document.documentElement;
    if (dark) {
      html.setAttribute('data-theme', 'dark');
    } else {
      // 显式设 'light', 方便 index.css 用 [data-theme="dark"] 单选择器匹配
      html.setAttribute('data-theme', 'light');
    }
  }, [dark]);

  return (
    <button
      type="button"
      onClick={() => setDark((d) => !d)}
      aria-label={dark ? '切换到明亮模式' : '切换到暗黑模式'}
      aria-pressed={dark}
      title={dark ? '当前: 暗黑模式 (点击切回明亮)' : '当前: 明亮模式 (点击切到暗黑)'}
      data-testid="theme-toggle"
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
      {/* 极简 glyph: 月亮 = 暗, 太阳 = 明 (academic editorial 不用 emoji) */}
      <span
        aria-hidden="true"
        className="inline-block w-3 h-3 rounded-full shrink-0"
        style={{
          backgroundColor: dark ? 'var(--sf-accent)' : 'transparent',
          border: `1px solid ${dark ? 'var(--sf-accent)' : 'var(--sf-text)'}`,
        }}
      />
      <span className="font-medium">{dark ? '暗' : '明'}</span>
    </button>
  );
}