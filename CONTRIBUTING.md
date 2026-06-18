# Contributing to ScholarFlow

## Setup

### Prerequisites
- Python 3.11+ (3.12 recommended)
- Node.js 20+ and npm
- Git

### v1 (production)

```bash
# Backend (port 8000)
cd backend
pip install -r requirements.txt
pip install -r ../requirements-dev.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Frontend (port 5173)
cd frontend
npm install
npm run dev
# open http://127.0.0.1:5173/
```

### v4 (experimental)

```bash
# Backend (port 9000)
cd newversion/backend
pip install -r requirements.txt
python -m uvicorn scholarflow_v3.app:create_app --factory --host 127.0.0.1 --port 9000

# Frontend (port 6173)
cd newversion/frontend
npm install
npm run dev
# open http://127.0.0.1:6173/
```

Or use `python scripts/scholarflow.py start [--v4]` for both at once.

## Code style

**Frontend**: TypeScript strict, React function components + hooks, Tailwind utility classes (no custom CSS files unless required for animations). Run `npm run typecheck` before pushing.

**Backend**: PEP 8, full type hints on public functions, Pydantic models for I/O, docstrings only on non-obvious helpers. Ruff + black for formatting.

## Tests

- Backend: `python -m pytest -q tests/` from the repo root.
- Add new tests under `tests/test_<module>.py` matching `<module>`'s path.
- E2E / Playwright scripts live in `tests/manual/` and are run directly, not via pytest.
- Coverage: `python -m pytest --cov=backend --cov-report=term-missing -q tests/` (see `COVERAGE.md` for the baseline).

## PR process

1. Open an issue first if the change is non-trivial (refactor, new feature).
2. Branch from `master`: `git checkout -b feat/R10.5.x-short-name`.
3. Commit messages reference the release tag: `feat(R10.5.40): ...`, `fix(R10.5.40): ...`.
4. Push the branch and open a PR against `master`. CI must be green (test / security / frontend / docker).
5. One approval + green CI = merge.

## Two-version policy

This repo ships **two parallel implementations** that coexist on different ports:

- **v1** in `backend/` + `frontend/src/` — production-style, real LangGraph + LLM calls, ports 8000/5173.
- **v4** in `newversion/` — experimental design exploration with a deterministic mock pipeline, ports 9000/6173.

They share **no code, no ports, no database**. v1 is the stable production version; v4 is a design experiment to validate a reading-first UI. Neither supersedes the other — both are maintained side by side. Pick whichever fits your use case, or run both to compare.

When contributing, decide which version your change targets and keep the boundary clean. Cross-version refactors require an ADR in `docs/ADR/`.