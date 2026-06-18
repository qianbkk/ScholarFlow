// Footer — live cost counter, tokens, elapsed. Tabular figures. 32px tall.

import { useEffect, useState } from 'react';
import { useStore } from '../hooks/useStore';

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export function Footer() {
  const { cost, tokens, startedAt, running, result, error } = useStore();
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!running || !startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [running, startedAt]);

  const elapsed = startedAt ? (now - startedAt) / 1000 : 0;
  const done = result ? result.elapsed_seconds : 0;
  const status = error ? 'err' : running ? 'run' : result ? 'done' : 'idle';

  return (
    <footer
      className="hairline-t flex items-center justify-between px-3 h-8"
      style={{ background: 'var(--base)' }}
    >
      <div className="flex items-center gap-4 mono text-[10px] tnum" style={{ color: 'var(--ink-2)' }}>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>cost</span>{' '}
          <span style={{ color: 'var(--ink-1)' }}>${cost.toFixed(4)}</span>
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>tokens</span>{' '}
          <span style={{ color: 'var(--ink-1)' }}>{tokens.toLocaleString()}</span>
        </span>
        <span>
          <span style={{ color: 'var(--ink-3)' }}>elapsed</span>{' '}
          <span style={{ color: 'var(--ink-1)' }}>{running ? fmt(elapsed) : fmt(done)}</span>
        </span>
        {result && (
          <span>
            <span style={{ color: 'var(--ink-3)' }}>iter</span>{' '}
            <span style={{ color: 'var(--ink-1)' }}>{result.iteration}</span>
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 mono text-[10px]" style={{ color: 'var(--ink-3)' }}>
        <span
          className="status-dot"
          style={{
            background:
              status === 'err'
                ? 'var(--signal-err)'
                : status === 'run'
                ? 'var(--accent)'
                : status === 'done'
                ? 'var(--signal-ok)'
                : 'var(--ink-3)',
          }}
        />
        <span className="uppercase" style={{ letterSpacing: '0.14em' }}>
          {status}
        </span>
      </div>
    </footer>
  );
}
