# ScholarFlow

A multi-agent literature survey tool. Ask a question, watch the pipeline work, get a cited report.

Two parallel implementations live in this repo:

- **v1 (production-style)** — `frontend/src/` + `backend/`, ports 5173 / 8000, real LangGraph pipeline, real LLM calls, full auth, BibTeX export.
- **v4 (experimental)** — `newversion/`, ports 6173 / 9000, deterministic mock pipeline, dark focus-first layout (one column + drawers, no three-column workspace), focused on whether a reading-first UI with inline paper cards works better for the research workflow.

Both run side by side. They share no code, share no ports, share no database. Pick whichever you want to use, or run both to compare.

## Quick start

### v4 (recommended for evaluation)

```bash
# Terminal 1 — backend on :9000
cd newversion/backend
pip install -r requirements.txt
python -m uvicorn scholarflow_v3.app:create_app --factory --host 127.0.0.1 --port 9000

# Terminal 2 — frontend on :6173 (proxies /api/* → :9000)
cd newversion/frontend
npm install
npm run dev
# open http://127.0.0.1:6173/
```

### v1 (original)

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Frontend
cd frontend
npm install
npm run dev
# open http://127.0.0.1:5173/
```

`scholarflow.bat` (Windows) wraps v1 start / stop / logs / install in a single menu.

## What it does

You type a question. An 8-node pipeline lights up:

1. **Decompose** — break the question into sub-questions.
2. **Refine** — strip filler, expand acronyms.
3. **Search** — retrieve candidate papers (Semantic Scholar / OpenAlex in v1; in-memory mock corpus in v3).
4. **Score** — rank by `0.6·relevance + 0.3·authority + 0.1·recency`.
5. **Extract** — pull claim sentences from abstracts.
6. **Gap** — surface coverage gaps.
7. **Critique** — caveat the candidate set.
8. **Synthesize** — assemble the cited Markdown report.

The output is a Markdown report with inline numbered citations, a D3 force-directed citation graph, and live cost / token / latency telemetry. Export to BibTeX and RIS in v1.

## v1 vs v3

| | v1 (`frontend/`, `backend/`) | v4 (`newversion/`) |
|---|---|---|
| Aesthetic | Light "scholar's workbench" — parchment + serif + library red | Dark "reading-first" — graphite + mono + sans + electric cyan |
| Layout | Three-column workspace (results / report / graph) | Single centered column + overlays (graph fullscreen, papers as right drawer) |
| Papers | In a left rail as a list | Inline in the report as expandable footnote cards |
| Pipeline | Real LangGraph 8 agents, real LLM calls | Deterministic mock, hash-seeded |
| API | `/api/v1/*` | `/api/v3/*` |
| Frontend port | 5173 | 6173 |
| Backend port | 8000 | 9000 |
| Auth | HttpOnly cookies + register / login | none (single-user) |
| BibTeX / RIS | yes | no |
| Goal | production use | parallel design exploration |

Both versions preserve the same 8-node pipeline shape, the same cost-telemetry surface, and the same Paper / Graph / SearchResult schema. v4 is a focused exploration: does reading-first (one column, papers inline, graph as an opt-in overlay) hold up better than workspace-first (three columns, everything visible)? Run them side by side and decide what to keep.

## Documentation

- `ROADMAP.md` — single source of truth for what's coming next. Replaces the older `docs/HANDOFF.md` / `docs/FUTURE_TASKS.md` (deleted R10.5.35).
- `newversion/PRODUCT.md` — product strategy for the v4 design exploration.
- `newversion/DESIGN.md` — visual system for v4 (colors, type, motion, layout, anti-patterns).
- `newversion/README.md` — detailed v4 architecture.
- `docs/ARCHITECTURE.md` — v1 backend architecture.
- `docs/DEPLOYMENT.md` — v1 deployment (systemd, Docker Compose, K8s).
- `.claude/skills/impeccable/` — the [pbakaus/impeccable](https://github.com/pbakaus/impeccable) design skill, installed locally for `/impeccable craft / shape / critique / audit / polish` commands.

## License

MIT. See `LICENSE`.

## Author

qianbkk — [github.com/qianbkk/ScholarFlow](https://github.com/qianbkk/ScholarFlow)
