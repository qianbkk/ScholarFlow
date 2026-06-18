// CommandBar — the largest interactive element. Wide, single-line input,
// "▶" submit affordance, ⌘↵ hint. Expands 2px on focus.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useStore } from '../hooks/useStore';
import { store } from '../state/store';
import { streamSearch } from '../services/api';

export function CommandBar() {
  const { query, running, result } = useStore();
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Cmd+K to focus, Esc to blur
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
      if (e.key === 'Escape' && document.activeElement === inputRef.current) {
        inputRef.current?.blur();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const run = async () => {
    if (!query.trim() || running) return;
    abortRef.current = new AbortController();
    store.startSearch();
    try {
      await streamSearch(
        { query },
        {
          signal: abortRef.current.signal,
          onNodeStart: (id) => store.updateNode(id, { status: 'running', started_at: Date.now() }),
          onNodeEnd: (id, _label, ok) =>
            store.updateNode(id, { status: ok ? 'done' : 'error', finished_at: Date.now() }),
          onCost: (cost, tokens) => store.setCost(cost, tokens),
          onPapers: () => store.pushEvent('papers', null),
          onRanked: () => store.pushEvent('ranked', null),
          onCritique: () => store.pushEvent('critique', null),
          onLog: () => store.pushEvent('log', null),
          onResult: (r) => store.finishSearch(r),
          onError: (e) => store.failSearch(e.message),
        },
      );
    } catch (err) {
      store.failSearch((err as Error).message);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      run();
    }
  };

  return (
    <div className="px-3 py-3 hairline-b" style={{ background: 'var(--base)' }}>
      <div
        className="flex items-center gap-2 px-3 h-11 transition-colors duration-150"
        style={{
          background: 'var(--surface-1)',
          borderBottom: focused ? '1px solid var(--accent)' : '1px solid var(--rule)',
        }}
      >
        <span
          className="mono"
          style={{ color: 'var(--accent)', fontSize: '14px' }}
          aria-hidden
        >
          ▶
        </span>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => store.setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={onKeyDown}
          disabled={running}
          placeholder={result ? 'Run another query' : 'Ask the literature'}
          className="flex-1 bg-transparent outline-none mono disabled:opacity-50"
          style={{
            fontFamily: '"Inter Tight", system-ui, sans-serif',
            fontSize: '15px',
            color: 'var(--ink-1)',
          }}
        />
        <span
          className="mono text-[10px] uppercase shrink-0"
          style={{ color: 'var(--ink-3)', letterSpacing: '0.14em' }}
        >
          ⌘↵ run
        </span>
      </div>
      {running && (
        <div
          className="mt-2 mono text-[10px] flex items-center gap-2"
          style={{ color: 'var(--ink-3)' }}
        >
          <span
            className="status-dot"
            style={{ background: 'var(--accent)' }}
            aria-hidden
          />
          <span>running 8-node pipeline</span>
        </div>
      )}
    </div>
  );
}
