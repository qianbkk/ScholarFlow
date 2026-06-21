# ScholarFlow

> **A multi-agent literature survey tool** — Ask a research question, watch the 8-node LangGraph pipeline work, get a cited report with a citation graph.

ScholarFlow is an opinionated research assistant that turns a natural-language question into a structured survey. A real LangGraph pipeline decomposes the query, searches five academic APIs (Semantic Scholar, OpenAlex, arXiv, Crossref, PubMed), expands citations, ranks by relevance / authority / consistency, refines iteratively, and synthesizes a Markdown report with numbered inline citations. Every step emits a thinking log you can watch in real time, every paper gets a D3 force-directed node in the citation graph, and the whole thing runs against real LLMs (no mock data unless you opt in).

---

## Table of contents

- [Highlights](#highlights)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [How a query flows](#how-a-query-flows)
- [Configuration](#configuration)
- [Frontend structure](#frontend-structure)
- [Backend structure](#backend-structure)
- [API surface](#api-surface)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Export](#export)
- [Internationalization](#internationalization)
- [Documentation](#documentation)
- [Release notes](#release-notes)
- [Author](#author)
- [Acknowledgments](#acknowledgments)

---

## Highlights

- **Real 8-node LangGraph pipeline** — `query_decompose → search → expand_citations → rank → refine → synthesize → build_graph → track_cost`, streamed over SSE.
- **5-source parallel search** — Semantic Scholar, OpenAlex, arXiv, Crossref, PubMed, deduped and re-ranked.
- **LLM-strict mode** — In LLM Search mode the ranker filters to `final_score ≥ 8` real papers, automatically relaxes to `≥ 7` on the next iteration if the corpus is thin, and never falls back to mock data.
- **Adjustable paper count** — Pick a `[min, max]` range from 3 to 30 papers per query (default 5–10).
- **Streaming thinking logs** — Each pipeline node appends reasoning steps that fade in on the cockpit; no opaque black box.
- **D3 citation graph** — Independent tab with year/author filter, 2-hop neighbor highlight, 8-color community palette, drag-to-pin, fit-to-view (`f`), fullscreen (`Shift+F`), rich tooltip.
- **Search summary + centered report** — The Search tab shows a summary card with the top 5 papers and a "view full report" link; the Report tab centers the rendered Markdown.
- **Settings drawer** — Language, theme, runtime mode, and API-key controls live in a persistent left sidebar that collapses on demand; About / changelog / shortcuts moved to a dedicated `About` tab.
- **Full i18n** — Every UI string is bilingual (Chinese default, English toggle); proper nouns like API Key, Author, BibTeX, Semantic Scholar stay in English.
- **Auth done properly** — Separate Register / Login tabs with seven distinct error messages, `/auth/revoke` for self-service key rotation, `/auth/logout` actually invalidates the session.
- **Pinned results** — PBKDF2-hashed passwords stored in a SQLite WAL database, HttpOnly session cookies with CSRF double-submit (see `docs/ADR/0001`).

## Quick start

### Prerequisites

- Python 3.12+
- Node.js 20+
- One LLM provider key (minimax / kimi / glm / Anthropic / DeepSeek)

### Backend (port 8000)

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env        # edit values
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

> For a one-shot start/stop/logs wrapper use `python scripts/scholarflow.py start` (cross-platform; see `scripts/scholarflow.py --help`).

### Frontend (port 5173)

```bash
cd frontend
npm install
npm run dev
# open http://127.0.0.1:5173/
```

Vite proxies `/api` to the backend, so no CORS configuration is required in development.

### Production build

```bash
cd frontend
npm run build                  # tsc + vite build, output in dist/
docker build -f Dockerfile.frontend -t scholarflow-frontend .
docker build -f Dockerfile.backend  -t scholarflow-backend  .
```

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for systemd, Docker Compose, and Kubernetes recipes.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Frontend — React 18 + TypeScript (strict) + Vite             │
│  14 components · single useStore · SSE client                 │
│  TopNav (5 tabs) + Settings sidebar + Command palette         │
└──────────────────────────────┬─────────────────────────────────┘
                               │  /api/v1/* (proxied in dev)
┌──────────────────────────────▼─────────────────────────────────┐
│  Backend — FastAPI + LangGraph                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 8-node pipeline (backend/agents/*.py)                   │  │
│  │ query_decompose → search → expand → rank → refine →     │  │
│  │ synthesize → build_graph → track_cost                   │  │
│  └─────────────────────────────────────────────────────────┘  │
│  Auth · Budget guard · Cost tracker · Cache · Rate limit      │
└──────────────────────────────┬─────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────┐
│  Data sources                                                   │
│  Semantic Scholar · OpenAlex · arXiv · Crossref · PubMed       │
│  (mock fallback ONLY when runtime_mode = "local")              │
└────────────────────────────────────────────────────────────────┘
```

For a deeper look at the backend design (state shape, router logic, cache strategy) see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## How a query flows

1. The user types a question in the Search tab and picks provider, budget (USD), max iterations, and the `[min, max]` paper count.
2. The frontend POSTs `/api/v1/search` and opens an SSE stream on `/api/v1/search/stream`.
3. The backend runs the LangGraph pipeline. Every node emits a `node_complete` event; every `_step()` call emits a `node_thinking` event so the user sees the reasoning in real time.
4. `query_decompose` splits the question into 3–5 sub-queries with structured constraints (year range, venues).
5. `search` fans the sub-queries out to all five APIs in parallel, then dedupes. In LLM Search mode fallback papers are dropped here.
6. `expand_citations` walks references and citations forward and backward with a `Semaphore(4)` rate limiter.
7. `rank` scores every paper on relevance / authority / consistency. In LLM Search mode it drops anything below the active threshold.
8. `refine` runs only when results are thin — generates more sub-queries and relaxes the score threshold (8.0 → 7.0).
9. `synthesize` calls the LLM to produce the Markdown report and validates that every `[N]` citation resolves to a paper in the ranked set.
10. `build_graph` produces the D3 graph (cites, co-cited, same venue, author overlap).
11. `track_cost` aggregates tokens, cost, and elapsed time.

## Configuration

All runtime configuration lives in `.env` (see `.env.example` for the full list). The most relevant keys:

| Variable | Purpose | Default |
|---|---|---|
| `OPEN_MODE` | Skip auth and use a synthetic dev user (development only) | `false` |
| `BUDGET_LIMIT_USD` | Default per-query budget cap | `2.0` |
| `MAX_SEARCH_ITERATIONS` | Default max refinement iterations | `3` |
| `MiniMax_API_KEY` / `KIMI_API_KEY` / `GLM_API_KEY` / `ANTHROPIC_API_KEY` | LLM provider keys | empty |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed origins | `http://127.0.0.1:5173` |

The Settings sidebar in the frontend exposes a subset of these (theme, runtime mode, API key) without restarting the backend; the rest live in `.env` and require a server restart.

## Frontend structure

```
frontend/src/
├── App.tsx                # top-level layout + global keybindings
├── commands.ts            # command palette registry
├── main.tsx               # React 18 entry + error boundary
├── index.css              # tokens + base styles
│
├── components/
│   ├── TopNav.tsx              # hamburger · wordmark · 5 tabs · user menu
│   ├── SearchWorkspace.tsx     # query input + summary card + paper list
│   ├── SearchSummary.tsx       # title + Top 5 + "view full report"
│   ├── ReportView.tsx          # centered Markdown + anchored papers
│   ├── GraphPage.tsx           # standalone D3 graph tab
│   ├── HistoryView.tsx         # recent searches + rerun
│   ├── AboutView.tsx           # about / shortcuts / changelog
│   ├── SettingsDrawer.tsx      # left sidebar (collapsed/expanded)
│   ├── AuthDialog.tsx          # register / login / rotate key / sign out
│   ├── CommandPalette.tsx      # Cmd/Ctrl-K palette
│   ├── ChangelogModal.tsx      # release notes overlay
│   ├── CompareDrawer.tsx       # side-by-side paper comparison
│   ├── PipelineProgress.tsx    # 8 ticks + thinking log + graph scrubber
│   ├── QueryInput.tsx          # textarea + provider/budget/iter/paper sliders
│   └── PaperList.tsx           # numbered paper list with selection
│
├── i18n/index.ts          # useT hook + Chinese/English dictionaries
├── store/useStore.ts      # single store (useSyncExternalStore)
├── lib/tokens.ts          # OKLCH theme tokens
├── lib/storageKeys.ts     # localStorage key registry
├── services/api.ts        # typed fetch wrappers + SSE client
└── types/index.ts         # shared TypeScript types
```

## Backend structure

```
backend/
├── main.py                # FastAPI app + lifespan + middleware
├── config.py              # env loading + defaults
├── middleware.py          # CORS + rate limit + trusted host
│
├── api/
│   ├── routes/
│   │   ├── search.py      # /search, /search/stream (SSE), /search/cancel
│   │   ├── auth.py        # register, login, logout, revoke, me, csrf
│   │   ├── admin.py       # admin-only runtime-mode switching
│   │   └── health.py      # /health, /providers
│   └── services/          # budget, providers, streaming helpers
│
├── agents/                # the 8-node LangGraph pipeline
│   ├── query_decomposer.py
│   ├── search_agent.py
│   ├── citation_expander.py
│   ├── ranker_agent.py
│   ├── query_refiner.py
│   ├── synthesis_agent.py
│   ├── graph_builder.py
│   ├── critic_agent.py
│   ├── cost_tracker.py
│   ├── _schemas.py        # Pydantic shared schemas + parse helpers
│   ├── _state_utils.py    # state pruning
│   └── _step_helper.py    # thinking-log helper
│
├── auth/                  # PBKDF2 + SQLite WAL + dependencies
├── models/                # Pydantic + TypedDict state shape
├── utils/                 # budget · cache · runtime_mode · sanitize · observability
└── workflow/              # LangGraph graph + router
```

## API surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/search` | Run a search synchronously (480 s timeout). |
| `GET` | `/api/v1/search/stream` | Run a search, stream SSE events. |
| `POST` | `/api/v1/search/cancel` | Cancel an in-flight search by `request_id`. |
| `POST` | `/api/v1/auth/register` | Create an account, returns API key. |
| `POST` | `/api/v1/auth/login` | Sign in, rotates key. |
| `POST` | `/api/v1/auth/logout` | Invalidate the session. |
| `POST` | `/api/v1/auth/revoke` | Self-service key rotation (requires auth). |
| `GET` | `/api/v1/auth/me` | Current user info. |
| `GET` | `/api/v1/auth/csrf-token` | CSRF double-submit token. |
| `GET` | `/api/v1/auth/stream-token` | Short-lived token for SSE handshakes. |
| `GET` | `/api/v1/health` | Health check (no auth). |
| `GET` | `/api/v1/providers` | List configured LLM providers. |
| `POST` | `/api/v1/admin/runtime-mode` | Admin-only runtime-mode switch. |

The SSE event vocabulary is documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#sse-event-vocabulary).

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Cmd/Ctrl + K` | Open the command palette |
| `Cmd/Ctrl + Enter` | Submit the current query |
| `Esc` | Close any open modal; in the Graph tab, clear the selection or exit fullscreen |
| `f` (Graph tab) | Fit the graph to view |
| `Shift + F` (Graph tab) | Toggle graph fullscreen |
| `?` | Show the shortcut overlay |

## Export

- **BibTeX** (`.bib`) — for Zotero, Mendeley, and any LaTeX-based pipeline.
- **RIS** (`.ris`) — for EndNote, RefMan, and most reference managers.
- **Markdown** (`.md`) — the raw report with inline `[N]` citations and anchored papers section.

The report tab includes `↓ .bib`, `↓ .ris`, and `↓ .md` download links.

## Internationalization

The interface is fully bilingual. The toggle is the `中 / EN` button in the top-right corner of the navigation bar.

| | Chinese (default) | English |
|---|---|---|
| Tabs | 查询 / 报告 / 图谱 / 历史 / 设置 | Search / Report / Graph / History / Settings |
| Pipeline | 查询分解 / 双源检索 / 引文扩展 / 三维排序 / 查询优化 / 综述生成 / 图谱构建 / 成本汇总 | Query decompose / Dual-source search / Citation expand / 3D rank / Query refine / Synthesize / Graph build / Cost track |

Proper nouns (Semantic Scholar, OpenAlex, API Key, Author, BibTeX, RIS) are kept in English in both locales. The dictionary lives in [`frontend/src/i18n/index.ts`](frontend/src/i18n/index.ts).

## Documentation

- [`BACKLOG.md`](BACKLOG.md) — single source of truth for outstanding cleanup, refactors, deferred P0/P1 items, and R11+ strategy.
- [`ROADMAP.md`](ROADMAP.md) — R11+ strategic direction and historical release log.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — backend architecture (state shape, node details, SSE vocabulary).
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — systemd, Docker Compose, Kubernetes.
- [`docs/ADR/`](docs/ADR/) — accepted architectural decisions:
  - [0001 — HttpOnly + SameSite=Strict session cookies with CSRF double-submit](docs/ADR/0001-http-only-session-cookies.md)
  - [0002 — Dual-version strategy](docs/ADR/0002-dual-version-strategy.md)
  - [0003 — Deterministic mock pipeline](docs/ADR/0003-deterministic-mock-pipeline.md)
- [`RELEASES.md`](RELEASES.md) — copy-paste-ready GitHub Release notes per version.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute.

## Release notes

The most recent five releases:

- **R10.5.59** (2026-06-21) — Hamburger Settings sidebar · adjustable paper count (3-30) · LLM Search strict score threshold (≥ 8 → relax ≥ 7) · Search summary card + centered Report · D3 graph hover-jitter fix · complete i18n coverage.
- **R10.5.55** (2026-06-21) — Chinese/English i18n · D3 graph as a standalone tab · Settings drawer replacing the Settings tab · `runtime_mode` renamed to `local` / `llm` · strict auth (register/login/revoke) · per-node thinking logs.
- **R10.5.54** (2026-06-20) — Frontend rebuild on the Editorial Desk Reference visual language · 14 components · single `useStore` replacing three React contexts and 13 `useState` hooks.
- **R10.5.53** (2026-06-20) — 4-tab routing · per-node thinking logs · graph evolution folded into the pipeline cockpit.
- **R10.5.51** (2026-06-19) — `/simplify` 8-item cleanup · `STORAGE_KEYS` centralization · `BACKLOG.md` consolidation.

The full per-version changelog lives in the in-app `ChangelogModal` and in [`RELEASES.md`](RELEASES.md).

## Author

**qianbkk** — [github.com/qianbkk/ScholarFlow](https://github.com/qianbkk/ScholarFlow)

## Acknowledgments

- Built on top of [LangGraph](https://langchain-ai.github.io/langgraph/) for the multi-agent pipeline.
- Powered by [OpenAlex](https://openalex.org), [Semantic Scholar](https://www.semanticscholar.org/), [arXiv](https://arxiv.org/), [Crossref](https://www.crossref.org/), and [PubMed](https://pubmed.ncbi.nlm.nih.gov/).
- UI follows the Editorial Desk Reference visual language; D3 powers the citation graph.
- Release engineering workflow informed by the [`create-readme`](https://github.com/github/awesome-copilot/tree/main/skills/create-readme) and [`readme-blueprint-generator`](https://github.com/github/awesome-copilot/tree/main/skills/readme-blueprint-generator) skills from the [`github/awesome-copilot`](https://github.com/github/awesome-copilot) community.