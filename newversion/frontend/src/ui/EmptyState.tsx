// EmptyState — the home. One large input field, centered, no chrome.
// This is what you see when you arrive and after you reset.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { store } from '../state/store';
import { streamSearch } from '../services/api';

export function EmptyState() {
  const { query, mode } = store.get();
  const [, force] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [focused, setFocused] = useState(false);

  // Cmd+K focuses, Esc blurs
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

  // Auto-focus on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const run = async () => {
    const q = store.get().query.trim();
    if (!q) return;
    abortRef.current = new AbortController();
    store.startSearch();
    try {
      await streamSearch(
        { query: q },
        {
          signal: abortRef.current.signal,
          onNodeStart: (id) => store.updateNode(id, { status: 'running', started_at: Date.now() }),
          onNodeEnd: (id, _label, ok) =>
            store.updateNode(id, { status: ok ? 'done' : 'error', finished_at: Date.now() }),
          onCost: (cost, tokens) => store.setCost(cost, tokens),
          // R10.5.51 cleanup (BACKLOG C-006): 4 SSE 回调占位, 暂未接 UI
          // (live log 没接), 改 console.debug 防 silent drop, 接口保留
          // 给将来 live log / papers-drawer 接入用.
          onPapers: (papers) => console.debug('[v4/stream] papers:', papers.length),
          onRanked: (ranked) => console.debug('[v4/stream] ranked:', ranked.length),
          onCritique: (critique) => console.debug('[v4/stream] critique:', critique.length),
          onLog: (line) => console.debug('[v4/stream] log:', line),
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
    <div
      className="flex-1 flex flex-col items-center justify-center px-6"
      style={{ background: 'var(--base)' }}
    >
      <div style={{ width: '100%', maxWidth: 'var(--read-max)' }}>
        <div
          className="mono text-[10px] uppercase mb-3"
          style={{ color: 'var(--ink-3)', letterSpacing: '0.22em' }}
        >
          ScholarFlow v4
        </div>

        <h1
          className="display m-0 mb-8"
          style={{
            fontSize: '1.4rem',
            fontWeight: 400,
            color: 'var(--ink-2)',
            letterSpacing: '-0.01em',
            lineHeight: 1.4,
          }}
        >
          Ask the literature. Watch it work.
        </h1>

        <div
          className="flex items-center gap-3 transition-colors duration-200"
          style={{
            padding: '20px 0',
            borderBottom: focused ? '1px solid var(--accent)' : '1px solid var(--rule-strong)',
          }}
        >
          <span
            className="mono shrink-0"
            style={{ color: 'var(--accent)', fontSize: '18px' }}
            aria-hidden
          >
            ▶
          </span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              store.setQuery(e.target.value);
              force((n) => n + 1);
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={onKeyDown}
            disabled={mode === 'running'}
            placeholder="What does the literature say about…"
            className="flex-1 bg-transparent outline-none"
            style={{
              fontFamily: '"Space Grotesk", system-ui, sans-serif',
              fontSize: '24px',
              fontWeight: 400,
              letterSpacing: '-0.015em',
              color: 'var(--ink-1)',
              border: 'none',
              padding: 0,
            }}
            aria-label="Query"
          />
        </div>

        <div
          className="mt-3 flex items-center justify-between mono text-[11px]"
          style={{ color: 'var(--ink-3)' }}
        >
          <span>
            <kbd
              className="mono"
              style={{
                background: 'var(--surface-1)',
                border: '1px solid var(--rule)',
                padding: '1px 6px',
                fontSize: '10px',
                color: 'var(--ink-2)',
              }}
            >
              ⌘↵
            </kbd>{' '}
            to run · 8-node pipeline · ~30s
          </span>
          <button
            type="button"
            onClick={run}
            disabled={mode === 'running' || !query.trim()}
            className="display"
            style={{
              background: 'transparent',
              color: query.trim() ? 'var(--accent)' : 'var(--ink-3)',
              border: 'none',
              padding: 0,
              fontSize: '14px',
              fontWeight: 500,
              letterSpacing: '-0.01em',
              cursor: query.trim() ? 'pointer' : 'default',
            }}
          >
            run →
          </button>
        </div>
      </div>
    </div>
  );
}
