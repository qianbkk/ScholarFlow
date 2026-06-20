# ADR 0002: Dual-version strategy — v1 production, v4 experimental, side by side

- **Status**: Superseded by R10.5.52 (2026-06-20) — v4 removed, v1 is the only version. ADR retained as historical record of the dual-version decision.
- **Originally Accepted**: R10.5.37 (2026-06-18)
- **Deciders**: Product / architecture track

## Context

v1 (`backend/` + `frontend/src/`) is feature-complete, CI-green, and stable — but its three-column cockpit layout is visually dated and we wanted to test a radically different UI hypothesis without committing to a rewrite. The question was: does a **reading-first** layout (single column + side drawers + inline paper cards) work better for the literature-survey workflow than the current **workspace-first** layout (three columns with persistent graph + cost + query panels)?

We had three options:

1. **Forced migration**: rebuild v1 in place. High risk — v1 is in production use by early adopters; regressions would be public.
2. **Branch + PR**: keep the experiment in a feature branch until "ready". Kills the iteration speed we needed — we wanted to A/B test side by side, not in a hidden branch.
3. **Parallel directories**: ship both in the same repo on different ports, with separate dependency trees, separate databases, and no shared code paths.

## Decision

Adopt option 3. v1 stays at `backend/` + `frontend/src/` (ports 8000/5173). v4 lives at `newversion/` (ports 9000/6173, frontend dev server 6173 proxies `/api` to backend 9000). They share **no Python modules, no Node packages, no database, no auth**. The only shared resource is the repo itself and the `scripts/` directory (cross-platform launcher).

The decision to switch to a "production" version will be made later, based on measured outcomes from real users testing both side by side. Until then, **neither supersedes the other**. The README, CONTRIBUTING, and this ADR all call this out explicitly so contributors don't accidentally try to merge the two.

## Consequences

**Positive**
- Zero risk to v1 stability — the experiment cannot break production.
- v4 can iterate on UX and design tokens freely without touching a green CI pipeline.
- A/B comparison is real: same researcher, same laptop, two browser tabs.
- New contributors can pick the version matching their interest (production hardening vs. UX exploration).

**Negative**
- 2x maintenance cost: two `requirements.txt`, two `package.json`, two Vite configs, two Playwright suites.
- Documentation has to repeat setup steps for both versions (mitigated by `scripts/scholarflow.py start [--v4]`).
- Risk of contributor confusion — addressed by the "Two-version policy" section in CONTRIBUTING.md and explicit `v1` / `v4` labels in commit messages since R10.5.30.

**Commits**: see `e7e8b6d` (R10.5.37 — v3 full rebuild into `newversion/`) and `2cee8bf` (R10.5.38 — v4 focus-first refactor). The dual-port scheme is documented in both `vite.config.ts` files and `scripts/scholarflow.py`.