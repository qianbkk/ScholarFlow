/**
 * CommandPalette — R10.5.54 Phase 4 完整实现
 *
 * Cmd+K 模态 + fuzzy filter + 键盘导航.
 * 命令注册表在 commands.ts, App 注入.
 */
import { useState, useMemo, useEffect, useRef } from 'react';
import { useStore, actions } from '../store/useStore';
import { buildCommands, type Command } from '../commands';
import { useT } from '../i18n';

interface Props {
  cycleTheme: () => void;
  cancelSearch: () => void;
}

function fuzzyMatch(query: string, target: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const t = target.toLowerCase();
  let i = 0;
  for (const ch of t) {
    if (ch === q[i]) i++;
    if (i === q.length) return true;
  }
  return false;
}

export function CommandPalette({ cycleTheme, cancelSearch }: Props) {
  const open = useStore((s) => s.commandPaletteOpen);
  const loading = useStore((s) => s.loading);
  const t = useT();
  const [query, setQuery] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const cmds: Command[] = useMemo(() => buildCommands({
    goToView: actions.setView,
    openSettings: actions.toggleSettingsCollapsed,
    cycleTheme,
    cancelSearch,
    openAuth: actions.openAuthDialog,
    openChangelog: actions.openChangelog,
    isLoading: loading,
    t,
  }), [loading, cycleTheme, cancelSearch, t]);

  const filtered = useMemo(() => {
    if (!query.trim()) return cmds;
    return cmds.filter((c) =>
      fuzzyMatch(query, c.label) ||
      fuzzyMatch(query, c.id) ||
      (c.keywords || []).some((k) => fuzzyMatch(query, k))
    );
  }, [cmds, query]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setSel(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    if (sel >= filtered.length) setSel(0);
  }, [filtered.length, sel]);

  if (!open) return null;

  const run = (c: Command) => {
    c.run();
    actions.closeCommandPalette();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSel((s) => Math.min(filtered.length - 1, s + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSel((s) => Math.max(0, s - 1));
    } else if (e.key === 'Enter' && filtered[sel]) {
      e.preventDefault();
      run(filtered[sel]);
    }
  };

  // 按 group 分组
  const groups = useMemo(() => {
    const m = new Map<string, Command[]>();
    for (const c of filtered) {
      const g = c.group || '';
      if (!m.has(g)) m.set(g, []);
      m.get(g)!.push(c);
    }
    return Array.from(m.entries());
  }, [filtered]);

  // 把 sel 转成 flat 索引用于高亮
  let runningIdx = -1;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: 96,
        backgroundColor: 'rgba(0, 0, 0, 0.4)',
      }}
      onClick={actions.closeCommandPalette}
    >
      <div
        className="sf-fade-in"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 480,
          maxWidth: 'calc(100vw - 48px)',
          backgroundColor: 'var(--sf-bg)',
          border: '1px solid var(--sf-border)',
          borderRadius: 4,
          padding: 0,
          maxHeight: '70vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKey}
          placeholder="Type a command…"
          aria-label="Command filter"
          className="font-ui"
          style={{
            width: '100%',
            padding: '14px 16px',
            border: 'none',
            borderBottom: '1px solid var(--sf-border)',
            backgroundColor: 'transparent',
            color: 'var(--sf-text)',
            fontSize: 15,
            outline: 'none',
          }}
        />

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {filtered.length === 0 && (
            <p
              className="font-body"
              style={{
                padding: '24px',
                fontSize: 13,
                color: 'var(--sf-muted)',
                fontStyle: 'italic',
                margin: 0,
              }}
            >
              no command matches
            </p>
          )}
          {groups.map(([g, list]) => (
            <div key={g || '_'} style={{ padding: '8px 0' }}>
              {g && (
                <div
                  className="font-mono"
                  style={{
                    padding: '4px 16px',
                    fontSize: 10,
                    color: 'var(--sf-muted)',
                    letterSpacing: '0.04em',
                  }}
                >
                  {g}
                </div>
              )}
              <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {list.map((c) => {
                  runningIdx++;
                  const isSel = runningIdx === sel;
                  return (
                    <li
                      key={c.id}
                      onClick={() => run(c)}
                      style={{
                        position: 'relative',
                        padding: '8px 16px',
                        cursor: 'pointer',
                        backgroundColor: isSel ? 'var(--sf-surface-alt)' : 'transparent',
                      }}
                      onMouseEnter={() => setSel(cmds.indexOf(c))}
                    >
                      {isSel && (
                        <span
                          aria-hidden
                          style={{
                            position: 'absolute',
                            left: 0,
                            top: 0,
                            bottom: 0,
                            width: 2,
                            backgroundColor: 'var(--sf-accent)',
                          }}
                        />
                      )}
                      <div className="font-ui" style={{ fontSize: 14, color: 'var(--sf-text)' }}>
                        {c.label}
                      </div>
                      {c.hint && (
                        <div className="font-body" style={{ fontSize: 12, color: 'var(--sf-muted)' }}>
                          {c.hint}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>

        <footer
          className="font-mono"
          style={{
            padding: '8px 16px',
            fontSize: 10,
            color: 'var(--sf-muted)',
            borderTop: '1px solid var(--sf-border)',
            display: 'flex',
            gap: 12,
          }}
        >
          <span>↑↓ navigate</span>
          <span>↵ run</span>
          <span>esc close</span>
        </footer>
      </div>
    </div>
  );
}