// QueryInput — the largest, most-honest element on screen.
// NOT a chat bubble, NOT a textarea. A single-line input that grows to 3 lines on focus.
// Returns the user's question in plain text.

import { useState, useRef, useEffect, type KeyboardEvent } from 'react';
import { useSearch } from '../contexts/SearchContext';

export function QueryInput() {
  const { state, setQuery, submit } = useSearch();
  const [focused, setFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow: 1 line at rest, up to 3 lines on focus / content.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 96)}px`;
  }, [state.query, focused]);

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit(state.query);
    }
  };

  const submitting = state.loading;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit(state.query);
      }}
      className="relative"
    >
      <label
        htmlFor="sf-query"
        className="mono block text-[11px] uppercase tracking-[0.18em] mb-2"
        style={{ color: 'var(--ink-3)' }}
      >
        Question
      </label>
      <div
        className="relative transition-colors duration-200 ease-out-expo"
        style={{
          background: 'var(--paper-elev)',
          borderBottom: focused ? '1px solid var(--accent)' : '1px solid var(--rule-strong)',
        }}
      >
        <textarea
          id="sf-query"
          ref={textareaRef}
          rows={1}
          value={state.query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={onKeyDown}
          disabled={submitting}
          placeholder="What does the literature say about…"
          className="w-full resize-none bg-transparent px-0 py-3 outline-none disabled:opacity-60"
          style={{
            fontFamily: '"Source Serif 4", Georgia, serif',
            fontSize: '1.35rem',
            lineHeight: 1.4,
            letterSpacing: '-0.015em',
            color: 'var(--ink)',
            minHeight: '52px',
          }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className="mono text-[11px]" style={{ color: 'var(--ink-3)' }}>
          <span className="kbd">⌘</span> <span className="kbd">↵</span> to run · 8-node pipeline, 30s–3min
        </span>
        <button
          type="submit"
          disabled={submitting || !state.query.trim()}
          className="mono text-[12px] uppercase tracking-[0.14em] px-4 py-1.5 transition-all duration-200 ease-out-expo disabled:opacity-40"
          style={{
            background: submitting ? 'var(--ink-2)' : 'var(--ink)',
            color: 'var(--paper)',
            border: '1px solid transparent',
          }}
        >
          {submitting ? 'Running' : 'Run'}
        </button>
      </div>
    </form>
  );
}
