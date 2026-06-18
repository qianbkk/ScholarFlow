# ScholarFlow v3 — newversion/

A complete, independent rewrite of ScholarFlow. Lives in `newversion/`, separate
from the v1 code at `frontend/src/` and `backend/` which remain untouched.

## What's different from v1

| | v1 (in `frontend/src/`, `backend/`) | v3 (this folder) |
|---|---|---|
| Aesthetic | Light "scholar's workbench" (parchment + serif) | Dark "control room" (graphite + mono + sans) |
| Accent | Library red (oxblood) | Electric cyan |
| State | 13 `useState` + 3 layered contexts | Single module-scope reactive store |
| API | `/api/v1/*` | `/api/v3/*` |
| Backend port | 8000 | 9000 |
| Frontend port | 5173 | 6173 |
| Pipeline source | 8 LangGraph agents, real LLM | 8 mock nodes, deterministic, hash-seeded |
| Auth | HttpOnly cookies + register/login | none (single-user mock) |
| BibTeX / RIS export | yes | no |
| Goal | Production | Parallel exploration — does the v3 design hold up? |

The two run side by side: start v1 on 5173, v3 on 6173, both proxy to their own
backend. They share `localhost` but no code.

## Run v3

Two terminals:

```bash
# Terminal 1 — backend (port 9000)
cd newversion/backend
pip install -r requirements.txt
python -m uvicorn scholarflow_v3.app:create_app --factory --host 127.0.0.1 --port 9000

# Terminal 2 — frontend (port 6173, proxies /api/* → :9000)
cd newversion/frontend
npm install
npm run dev
```

Then open http://127.0.0.1:6173/.

## Design intent

See `newversion/PRODUCT.md` (who/why) and `newversion/DESIGN.md` (how it looks).
The short version: dark by default, mono + sans only, electric cyan accent, 8-node
pipeline strip always visible, command bar at top, three dense panels, footer with
live cost. No serif (v1 trap). No library red (v2 trap). No cream/sand body bg.
No SaaS hero-metric tiles. No "01 / 02 / 03" eyebrows. No gradient text. No
glassmorphism. No hover scale on images.

## Backend (port 9000)

`/api/v3/*`:

- `GET /health` — `{ status, version, nodes, uptime }`
- `POST /search` — runs the 8-node pipeline to completion, returns full result
- `POST /search/stream` — SSE stream of `node_start` / `node_end` / `cost` / `papers` / `ranked` / `critique` / `log` events, then a final `result` event
- `POST /search/cancel` — cancel a running search by id

The 8 nodes, in order:
1. `query_decomposer` — break the question into sub-questions
2. `query_refiner` — strip filler, expand acronyms
3. `paper_searcher` — search the in-memory corpus
4. `relevance_scorer` — `0.6*relevance + 0.3*authority + 0.1*recency`
5. `evidence_extractor` — pull claim sentences from abstracts
6. `gap_analyzer` — surface coverage gaps
7. `critic` — caveat the candidate set
8. `synthesis` — assemble the Markdown report

The pipeline is deterministic: same query → same paper subset, same scores, same
report. Hash-seeded. No network calls. No LLM. Replace with real implementations
when ready.

## Frontend (port 6173)

```
newversion/frontend/
├── index.html / package.json / tsconfig.json / vite.config.ts / tailwind.config.js / postcss.config.js
└── src/
    ├── main.tsx, App.tsx
    ├── styles/tokens.css         ← OKLCH palette, motion, prose styles
    ├── types.ts                  ← mirrors backend models
    ├── services/api.ts           ← SSE stream parser
    ├── state/store.ts            ← single module-scope reactive store
    ├── hooks/
    │   ├── useStore.ts           ← subscribe-to-store hook
    │   └── useTheme.ts           ← dark/light toggle
    └── components/
        ├── TopBar.tsx
        ├── PipelineStrip.tsx     ← always-visible 8-node row
        ├── CommandBar.tsx        ← query input + ⌘K to focus
        ├── ResultsPanel.tsx      ← dense paper list
        ├── ReportPanel.tsx       ← Markdown + inline citations
        ├── GraphPanel.tsx        ← D3 force, Viridis by year
        ├── CompareBar.tsx        ← 2-paper side-by-side
        └── Footer.tsx            ← live cost counter
```

## What's preserved

- The 8-node pipeline shape. The names are the same. The cost-telemetry
  surface is the same.
- The 4xx/5xx SSE event taxonomy.
- The Paper / Graph / SearchResult schema (simplified, no model_usage_summary,
  no BibTeX).

## What's intentionally missing (for this exploration)

- Real LLM calls (the v3 backend is a deterministic mock).
- Auth, sessions, multi-user.
- BibTeX / RIS export.
- Light theme is wired but not the default; a future build could swap.
- i18n, mobile, virtualization.

These are all things the v1 has. The v3 is a focused exploration: does the
**dark control-room aesthetic + always-visible pipeline + mono data** hold up
for the research workflow? Compare side by side, decide what to keep.
