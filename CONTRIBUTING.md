# Contributing to ScholarFlow

## Setup

### Prerequisites
- Python 3.11+ (3.12 recommended)
- Node.js 20+ and npm
- Git

### Local development

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

Or use `python scripts/scholarflow.py start` (cross-platform launcher) to wrap v1 start / stop / logs / install in a single command.

## Code style

**Frontend**: TypeScript strict, React function components + hooks, Tailwind utility classes (no custom CSS files unless required for animations). Run `npm run typecheck` before pushing.

**Backend**: PEP 8, full type hints on public functions, Pydantic models for I/O, docstrings only on non-obvious helpers. Ruff + black for formatting.

## Tests

- Backend: `python -m pytest -q tests/` from the repo root.
- Add new tests under `tests/test_<module>.py` matching `<module>`'s path.
- E2E / Playwright scripts live in `tests/manual/` and are run directly, not via pytest.
- Coverage: `python -m pytest --cov=backend --cov-report=term-missing -q tests/` (requires `pytest-cov`; not in CI baseline since `H-001` is pending online env).

## PR process

1. Open an issue first if the change is non-trivial (refactor, new feature).
2. Branch from `master`: `git checkout -b feat/R10.5.x-short-name`.
3. Commit messages reference the release tag: `feat(R10.5.40): ...`, `fix(R10.5.40): ...`.
4. Push the branch and open a PR against `master`. CI must be green (test / security / frontend / docker).
5. One approval + green CI = merge.

## Single-version policy

This repo ships **one implementation**: `backend/` + `frontend/`. v1 is the only version.

When contributing, target v1. New architectural decisions require an ADR in `docs/ADR/`.