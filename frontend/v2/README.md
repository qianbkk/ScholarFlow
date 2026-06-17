# ScholarFlow v2 — front-end

A complete rebuild of the ScholarFlow front-end from scratch, using the [`impeccable`](https://github.com/pbakaus/impeccable) design system as the visual north star. The previous front-end (`../src/`) is **untouched** — v2 lives entirely under `frontend/v2/`.

## Design intent

See `DESIGN.md` and `PRODUCT.md` at the project root for the full design system and product context. In short:

- **Scholarly restraint.** Type-led, ink-on-paper. No marketing flourish.
- **Methodical transparency.** Cost, tokens, status, and node progress are always visible.
- **Citation as first-class content.** Inline numbered citations link to a references section with DOIs.
- **Color-blind safe.** Viridis ramp on the citation graph, never red/green only distinctions.
- **Reduced motion.** `prefers-reduced-motion: reduce` honored.

Banned: side-stripe borders, gradient text, glassmorphism as a default, hero-metric tiles, identical card grids, eyebrow text on every section, "01/02/03" numbered scaffolding, hover scale on images, `Inter` as the only font, cream/sand body backgrounds.

## Layout

- Top: a sticky status bar (papers / nodes / tokens / cost / elapsed) with a live progress strip below it.
- Left rail: query input, then the ranked paper list.
- Center: the Markdown report with inline citations, references, and a compare drawer that appears when two papers are selected.
- Right rail: the D3 force-directed citation graph (Viridis by year, hover highlights 1-hop neighborhood).

Single-region dominance: the center column caps at 75ch for reading. Side rails scroll independently.

## Run locally

```bash
cd frontend/v2
npm install
npm run dev
```

The dev server proxies `/api/*` to the v1 backend at `http://127.0.0.1:8000`. Start the v1 backend first (`scholarflow.bat` or `uvicorn backend.main:app`).

## File map

```
frontend/v2/
├── index.html
├── package.json
├── tailwind.config.js
├── tsconfig.json
├── vite.config.ts
└── src/
    ├── main.tsx                  # entry
    ├── App.tsx                   # provider wrapper
    ├── styles/tokens.css         # design tokens (OKLCH palette, type, motion)
    ├── services/api.ts           # /api/v1/* client + SSE stream parser
    ├── contexts/
    │   ├── SearchContext.tsx     # query / result / progress / cost reducer
    │   └── SelectionContext.tsx  # multi-select papers for compare
    ├── components/
    │   ├── QueryInput.tsx        # the largest, most-honest element
    │   ├── StatusBar.tsx         # top sticky strip
    │   ├── PaperList.tsx         # numbered rows, hairline rules, no cards
    │   ├── ReportView.tsx        # Markdown + inline citations + references
    │   ├── CitationGraph.tsx     # D3 force layout, Viridis, hover highlight
    │   └── CompareDrawer.tsx     # 2-paper side-by-side, sticky at bottom
    ├── pages/
    │   └── Workspace.tsx         # 3-region layout
    └── types/
        └── domain.ts             # Paper / GraphNode / SearchResult
```

## What changed from v1

- One CSS-token file (`styles/tokens.css`) drives all colors, fonts, motion. No raw hex anywhere else.
- One `SearchContext` and one `SelectionContext` replace 13 `useState`s and three layered contexts.
- The query input is a single growing textarea (1→3 lines), not a chat bubble.
- The status bar is one row, mono, with a live progress strip below — not a hero-metric tile.
- The paper list is numbered rows with hairline rules — not a card grid.
- The graph uses Viridis by year (color-blind safe) and a 1-hop hover highlight.

## What v1 keeps

- The 8-node LangGraph pipeline (backend).
- The `/api/v1/*` URL contract.
- The same `SearchResult` shape.
- The same mock data fallback for offline / budget-exhausted runs.
