// API client — calls backend at /api/v1/*
// v2 uses the same backend (v1 unchanged). Cookie credentials for HttpOnly session.

import type { SearchResult, StreamEvent } from '../types/domain';

const API_BASE = '/api/v1';

interface StartSearchOptions {
  query: string;
  max_papers?: number;
  top_k?: number;
  budget_usd?: number;
  onEvent: (e: StreamEvent) => void;
  onError: (err: Error) => void;
  onDone: (result: SearchResult) => void;
  signal?: AbortSignal;
}

export async function startSearch(opts: StartSearchOptions): Promise<void> {
  const { query, max_papers, top_k, budget_usd, onEvent, onError, onDone, signal } = opts;
  const res = await fetch(`${API_BASE}/search/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      max_papers: max_papers ?? 20,
      top_k: top_k ?? 10,
      budget_usd: budget_usd ?? 0.50,
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    onError(new Error(`Search failed: ${res.status} ${res.statusText}`));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Parse SSE frames: lines beginning with "data: " separated by blank lines.
    let frameEnd: number;
    while ((frameEnd = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, frameEnd);
      buffer = buffer.slice(frameEnd + 2);
      const line = frame.split('\n').find((l) => l.startsWith('data: '));
      if (!line) continue;
      const payload = line.slice(6);
      if (payload === '[DONE]') continue;
      try {
        const parsed = JSON.parse(payload) as StreamEvent | SearchResult;
        // Heuristic: final result has a "ranked_papers" field.
        if ('ranked_papers' in parsed) {
          onDone(parsed as SearchResult);
        } else {
          onEvent(parsed as StreamEvent);
        }
      } catch {
        // Ignore malformed events.
      }
    }
  }
}

export async function cancelSearch(searchId: string): Promise<void> {
  await fetch(`${API_BASE}/search/cancel`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ search_id: searchId }),
  });
}

export async function fetchHealth(): Promise<{ status: string; version?: string }> {
  const res = await fetch(`${API_BASE}/health`, { credentials: 'include' });
  if (!res.ok) throw new Error('health failed');
  return res.json();
}

export async function summarizePaper(paperId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/agents/summarize`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_id: paperId }),
  });
  if (!res.ok) throw new Error(`summarize failed: ${res.status}`);
  const data = await res.json();
  return data.summary as string;
}

export async function critiquePaper(paperId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/agents/critique`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_id: paperId }),
  });
  if (!res.ok) throw new Error(`critique failed: ${res.status}`);
  const data = await res.json();
  return data.critique as string;
}
