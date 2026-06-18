// Header — top 36px, hairline bottom.
// Logo on the left, theme toggle on the right, horizontal progress line
// in the center that lights up as nodes complete. No always-visible
// 8-node strip — just one line.

import { useStore } from '../hooks/useStore';
import { useTheme } from '../hooks/useTheme';
import { store } from '../state/store';

function Glyph({ status }: { status: string }) {
  if (status === 'done') return <span className="mono" style={{ color: 'var(--signal-ok)' }}>✓</span>;
  if (status === 'error') return <span className="mono" style={{ color: 'var(--signal-err)' }}>✕</span>;
  if (status === 'running') return <span className="mono" style={{ color: 'var(--accent)' }}>●</span>;
  return <span className="mono" style={{ color: 'var(--ink-3)' }}>○</span>;
}

export function Header() {
  const { nodes, mode } = useStore();
  const { theme, setTheme } = useTheme();
  return (
    <header
      className="hairline-b flex items-center justify-between px-6 h-9 shrink-0"
      style={{ background: 'var(--base)' }}
    >
      <button
        type="button"
        onClick={() => store.reset()}
        className="flex items-center gap-2.5"
        style={{ background: 'transparent', border: 'none', padding: 0, cursor: 'pointer' }}
      >
        <span
          className="display text-[14px]"
          style={{ color: 'var(--ink-1)', fontWeight: 500, letterSpacing: '-0.01em' }}
        >
          ScholarFlow
        </span>
        <span
          className="mono text-[10px] uppercase"
          style={{ color: 'var(--ink-3)', letterSpacing: '0.18em' }}
        >
          v4
        </span>
      </button>

      {/* Center: horizontal progress line. Always visible. Each node is a dot. */}
      <ol
        className="flex items-center m-0 p-0 list-none"
        style={{ gap: 6 }}
        aria-label="pipeline progress"
      >
        {nodes.map((n, i) => (
          <li key={n.node_id} className="flex items-center">
            <span
              aria-label={n.label}
              title={`${i + 1}. ${n.label}`}
              style={{ fontSize: '10px' }}
            >
              <Glyph status={n.status} />
            </span>
            {i < nodes.length - 1 && (
              <span
                aria-hidden
                className="mx-1.5"
                style={{
                  display: 'inline-block',
                  width: 12,
                  height: 1,
                  background:
                    n.status === 'done' ? 'var(--rule-strong)' : 'var(--rule)',
                }}
              />
            )}
          </li>
        ))}
      </ol>

      <div className="flex items-center gap-2">
        {mode === 'done' && (
          <span
            className="mono text-[10px] uppercase"
            style={{ color: 'var(--signal-ok)', letterSpacing: '0.18em' }}
          >
            ready
          </span>
        )}
        <button
          type="button"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className="mono text-[10px] uppercase"
          style={{
            background: 'transparent',
            color: 'var(--ink-2)',
            border: '1px solid var(--rule-strong)',
            padding: '2px 8px',
            letterSpacing: '0.14em',
          }}
        >
          {theme === 'dark' ? 'light' : 'dark'}
        </button>
      </div>
    </header>
  );
}
