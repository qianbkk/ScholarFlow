// v3 API client. Calls the v3 backend at /api/v3/* via the vite proxy.

import type { LiveEvent, SearchResult } from '../types';

const API_BASE = '/api/v3';

export interface SearchParams {
  query: string;
  max_papers?: number;
  top_k?: number;
  budget_usd?: number;
}

export interface SearchHandlers {
  onNodeStart: (nodeId: string, label: string, index: number) => void;
  onNodeEnd: (nodeId: string, label: string, ok: boolean) => void;
  onCost: (costUsd: number, tokens: number) => void;
  onPapers: (papers: unknown[]) => void;
  onRanked: (papers: unknown[]) => void;
  onCritique: (text: string) => void;
  onLog: (text: string) => void;
  onResult: (result: SearchResult) => void;
  onError: (err: Error) => void;
  signal?: AbortSignal;
}

export async function streamSearch(params: SearchParams, h: SearchHandlers): Promise<void> {
  const res = await fetch(`${API_BASE}/search/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: params.query,
      max_papers: params.max_papers ?? 20,
      top_k: params.top_k ?? 10,
      budget_usd: params.budget_usd ?? 0.50,
    }),
    signal: h.signal,
  });

  if (!res.ok || !res.body) {
    h.onError(new Error(`HTTP ${res.status} ${res.statusText}`));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let end: number;
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const line = frame.split('\n').find((l) => l.startsWith('data: '));
        if (!line) continue;
        const raw = line.slice(6);
        if (raw === '') continue;
        let parsed: LiveEvent | { event: string; data: SearchResult } | { done: true };
        try {
          parsed = JSON.parse(raw);
        } catch {
          continue;
        }
        const ev = (parsed as LiveEvent).event;
        const data = (parsed as LiveEvent).data;

        if (ev === 'search_start') continue;
        if (ev === 'node_start') {
          h.onNodeStart(String(data.node_id), String(data.label), Number(data.index));
        } else if (ev === 'node_end') {
          h.onNodeEnd(String(data.node_id), String(data.label), Boolean(data.ok));
        } else if (ev === 'cost') {
          h.onCost(Number(data.cost_usd ?? 0), Number(data.tokens ?? 0));
        } else if (ev === 'papers') {
          h.onPapers((data as { papers: unknown[] }).papers);
        } else if (ev === 'ranked') {
          h.onRanked((data as { papers: unknown[] }).papers);
        } else if (ev === 'critique') {
          h.onCritique(String((data as { text: string }).text));
        } else if (ev === 'log') {
          h.onLog(String((data as { node: string }).node));
        } else if (ev === 'result') {
          h.onResult((data as { data: SearchResult }).data as unknown as SearchResult);
          return;
        } else if (ev === 'cancelled') {
          h.onError(new Error('cancelled'));
          return;
        }
      }
    }
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      h.onError(new Error('aborted'));
    } else {
      h.onError(err as Error);
    }
  }
}

export async function fetchHealth(): Promise<{ status: string; version: string; nodes: number }> {
  const r = await fetch(`${API_BASE}/health`);
  if (!r.ok) throw new Error('health failed');
  return r.json();
}
