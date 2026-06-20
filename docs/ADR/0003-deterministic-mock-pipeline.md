# ADR 0003: Deterministic hash-seeded mock pipeline for v4

- **Status**: Superseded by R10.5.52 (2026-06-20) — v4 removed, the deterministic mock pipeline it described is no longer part of the codebase. ADR retained as historical record of the v4 design rationale.
- **Originally Accepted**: R10.5.37 (2026-06-18)
- **Deciders**: v4 architecture track

## Context

The v4 design exploration (`newversion/`) needs to demo a credible 8-node research pipeline (decomposer → searcher → ranker → reader → synthesizer → critic → formatter → exporter) without paying for or waiting on real LLM calls. Real-API demos are slow (30–90 s per query), expensive, and **non-reproducible** — the same question asked twice returns different papers, different critiques, different reports. That made A/B testing between layouts impossible: you couldn't tell whether a UX change moved the needle or whether the LLM just rolled different dice.

We also needed v4 unit tests to run hermetically in CI without API keys. Every test that hit a real `anthropic.Anthropic()` client either skipped, mocked at the import level, or burned CI minutes on network calls.

## Decision

v4's backend uses a **deterministic, hash-seeded mock pipeline**. The seed is derived from the input query string via SHA-256; the mock deterministically produces the same papers, citations, report text, and critique for the same input. The implementation lives in `newversion/backend/scholarflow_v3/pipeline.py` behind the same node interface the real pipeline will eventually expose.

- Each node takes `(state, seed)` and returns the next state deterministically.
- `seed = int.from_bytes(sha256(query).digest()[:8], "big")` — same query → same seed → same output.
- The 8 nodes run sequentially in-process with the same async surface as LangGraph so swapping in real LLM calls later is a one-file change.

## Consequences

**Positive**
- v4 demos are bit-for-bit reproducible: same query, same screenshot, same report text.
- Unit tests need no API keys, no network, no SDK monkeypatching — they just call the pipeline and assert on output structure.
- CI for v4 runs in seconds, not minutes.
- Swapping to real LLMs is a **single-file change**: replace `pipeline.py` with a LangGraph-backed implementation that honours the same `(state, seed) -> state` contract. No frontend, no API, no test changes required.

**Negative**
- The mock can drift from real-LLM behaviour. We mitigate by keeping the mock's output schema identical to the real one's and writing tests on the schema, not the prose.
- Determinism means no surprise discoveries or hallucinations to navigate around in demos. We call this out in the v4 README so reviewers don't over-credit the UX for the predictability.

**Commits**: see `e7e8b6d` (R10.5.37 — v3 full rebuild, mock pipeline introduced) and `2cee8bf` (R10.5.38 — v4 focus-first refactor that exercised the determinism).