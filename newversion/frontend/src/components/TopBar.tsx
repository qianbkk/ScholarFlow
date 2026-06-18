// TopBar — app name + theme toggle + connection dot. 36px tall.

import { useStore } from '../hooks/useStore';
import { useTheme } from '../hooks/useTheme';

export function TopBar() {
  const { result } = useStore();
  const { theme, setTheme } = useTheme();
  return (
    <header
      className="hairline-b flex items-center justify-between px-3 h-9"
      style={{ background: 'var(--base)' }}
    >
      <div className="flex items-center gap-3">
        <span
          className="display text-[14px] font-medium"
          style={{ color: 'var(--ink-1)', letterSpacing: '-0.01em' }}
        >
          ScholarFlow
        </span>
        <span
          className="mono text-[10px] uppercase"
          style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
        >
          v3
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className="status-dot"
          style={{ background: result ? 'var(--signal-ok)' : 'var(--ink-3)' }}
        />
        <button
          type="button"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className="mono text-[10px] uppercase px-2 py-0.5"
          style={{
            background: 'transparent',
            color: 'var(--ink-2)',
            border: '1px solid var(--rule-strong)',
            letterSpacing: '0.14em',
          }}
        >
          {theme === 'dark' ? 'light' : 'dark'}
        </button>
      </div>
    </header>
  );
}
