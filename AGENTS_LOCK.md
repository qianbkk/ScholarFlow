# Parallel Agents Lock (R10.5.40 mega-refactor)

5 agents working concurrently. Each owns a slice of the codebase; touching
files outside your slice = bug. **READ THIS BEFORE EDITING.**

## Slice map

| Agent | Owns (ONLY edit these) | DO NOT touch |
|---|---|---|
| **Agent 1 (Phase 2: 主题/布局/内联卡)** | `frontend/src/App.tsx`, `frontend/src/components/CockpitDashboard.tsx`, `frontend/src/components/ReportPanel.tsx`, `frontend/src/components/QueryPanel.tsx`, `frontend/src/hooks/useLocalStorage.ts`, `frontend/src/lib/storageKeys.ts`, **NEW**: `frontend/src/components/InlinePaperCard.tsx`, `frontend/src/components/ThemeToggle.tsx`, `frontend/src/components/LayoutToggle.tsx`, `frontend/src/components/PipelineStrip.tsx` | `backend/**`, `newversion/**`, `tests/**`, `GraphPanel.tsx` (Agent 4), `frontend/src/components/CostDashboard.tsx` (Agent 4's domain via export hook if used) |
| **Agent 2 (shared/ 抽取)** | **NEW**: `backend/shared/__init__.py`, `backend/shared/paper_model.py`, `backend/shared/pipeline_state.py`. Plus re-export shims in `backend/models/__init__.py` so existing imports still work. | Don't move `backend/api/**`, `backend/agents/**`, `backend/auth/**` — they stay in place. shared/ is additive. |
| **Agent 3 (Phase 4: 测试+文档+脚本)** | `tests/**` (add new files only, don't modify existing), **NEW**: `CONTRIBUTING.md`, `docs/ADR/0001-0003.md`, `scripts/scholarflow.py`, `pyproject.toml` (add pytest-cov), `.github/workflows/*.yml` (add coverage step) | Don't touch application code. Don't add new tests that import from `frontend/src/` or `newversion/`. |
| **Agent 4 (Phase 5: 图谱+EndNote)** | `frontend/src/components/GraphPanel.tsx`, `frontend/src/services/api.ts` (only the export-related endpoints if any), `backend/utils/export.py`, **NEW**: `backend/utils/endnote.py`, `tests/test_endnote.py` | Don't touch `App.tsx` or `ReportPanel.tsx` (Agent 1's), don't touch `backend/agents/**` |
| **Agent 5 (simplify + code-review)** | Read-only on the working tree. Runs `/simplify` (4 cleanup agents in parallel) and `/code-review` (7 finders in parallel) on the diff of `git diff e7e8b6d..HEAD`. Returns findings only — does NOT edit code. | Strictly read-only. Findings go in `R10_5_40_REVIEW.md` at the project root. |

## Coordination rules

1. **No file is owned by two agents.** If you need to read a file outside your slice, read it. Don't write.
2. **App.tsx split risk**: Agent 1 owns App.tsx, Agent 5 will review it. That's fine.
3. **GraphPanel touchpoints**: Agent 4 owns GraphPanel. Agent 1's `ThemeToggle` may want to dispatch events into GraphPanel — Agent 1 should pass via a CSS class on the SVG root instead, not import GraphPanel internals.
4. **search_agent.py**: Agent 2 may extract pipeline state into shared/. Agent 5 may flag issues in search_agent.py. Agent 1 doesn't touch backend. Agent 4 doesn't touch backend/agents. So search_agent.py has exactly 1 mutator (Agent 2 via shared/), plus Agent 5 read-only review.
5. **export.py**: Agent 4 owns it. If Agent 1 needs export, it goes through the API, not the file.
6. **package.json / requirements.txt**: Each agent can add to dependencies needed for their slice. **Avoid duplicating**: if pytest-cov is in dev deps (Agent 3), other agents don't re-add it.

## Failure mode

If two agents DO conflict at write time, the second writer wins. The user
will see in the final review which files were clobbered. To prevent this,
before commit we will:
- `git diff --stat HEAD` to see all touched files
- Check overlap against the slice map
- Resolve any cross-slice edits by hand

## Commit message

One commit at the end:

```
feat(R10.5.40): 5-agent parallel mega-refactor — Phase 2/4/5 + shared + review

- Agent 1 (Phase 2): dark/light theme + 3-col/single-col layout switch +
  inline paper cards + streaming 8-node pipeline strip in v1 frontend
- Agent 2 (shared/): extract Paper model + pipeline state to backend/shared/
  for v1+v4 reuse
- Agent 3 (Phase 4): pytest-cov baseline + CONTRIBUTING.md + 3 ADRs +
  cross-platform scholarflow.py
- Agent 4 (Phase 5): interactive graph (1-hop/2-hop highlight + filter) +
  EndNote XML export
- Agent 5 (simplify + code-review): R10.5.36..HEAD diff, 11 cleanup
  findings, 5 review findings
```
