# Coverage baseline (R10.5.40)

## Run

```bash
python -m pytest --cov=backend --cov-report=term-missing -q tests/
```

(The `addopts` in `pytest.ini` make this the default `pytest` invocation too.)

## Headline number

**Coverage run deferred** — `pytest-cov` could not be installed in this environment (network egress to PyPI is blocked at the firewall, see `pip install pytest-cov` error: "No matching distribution found"). The dependency is correctly declared in `requirements-dev.txt` (`pytest-cov>=4.0.0`) and the CLI flag is wired into `pytest.ini`'s `addopts`. Re-run the command above in an environment with PyPI access to populate this number.

## Test baseline (without coverage)

Run `python -m pytest -q tests/` on 2026-06-18 against HEAD = R10.5.39 (pre-Phase 2/4/5 refactor):

- **588 passed, 1 skipped, 1 failed** in 10m 37s
- 1 failure: `tests/test_r10_5_29_simplify_fixes.py::test_query_panel_imports_recent_entry_and_runtime_mode` (pre-existing, unrelated to R10.5.40)

## Lowest-covered modules (post-refactor estimate)

These are the modules Agent 5's review flagged as under-tested; expect them to dominate the missing-lines column once `pytest-cov` runs:

1. `backend/api/v1/` (route handlers — most logic delegated to agents, low per-line coverage)
2. `backend/auth/` (auth + CSRF — exercised by `test_auth_api_key.py` only)
3. `backend/middleware.py` (request_id, rate limiter, audit log)
4. `backend/workflow/` (LangGraph orchestration; mostly integration-tested)
5. `newversion/backend/scholarflow_v3/pipeline.py` (v4 mock — see ADR 0003)

## How to drive the number up

Don't, for this baseline. The refactor goal was to **establish a number, not chase it**. Future tickets (R10.5.41+) can target specific low-coverage modules listed above.