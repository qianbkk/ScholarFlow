# ScholarFlow

A multi-agent literature survey tool. Ask a question, watch the pipeline work, get a cited report.

`backend/` + `frontend/` form the production app — real LangGraph pipeline, real LLM calls, full auth, BibTeX / RIS export.

## Quick start

```bash
# Backend on :8000
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Frontend on :5173
cd frontend
npm install
npm run dev
# open http://127.0.0.1:5173/
```

`python scripts/scholarflow.py start` (cross-platform launcher) wraps v1 start / stop / logs / install in a single command. Run `python scripts/scholarflow.py --help` for subcommands.

## What it does

You type a question. An 8-node pipeline lights up:

1. **Decompose** — break the question into sub-questions.
2. **Refine** — strip filler, expand acronyms.
3. **Search** — retrieve candidate papers (Semantic Scholar / OpenAlex).
4. **Score** — rank by `0.6·relevance + 0.3·authority + 0.1·recency`.
5. **Extract** — pull claim sentences from abstracts.
6. **Gap** — surface coverage gaps.
7. **Critique** — caveat the candidate set.
8. **Synthesize** — assemble the cited Markdown report.

The output is a Markdown report with inline numbered citations, a D3 force-directed citation graph, and live cost / token / latency telemetry. Export to BibTeX and RIS.

## Documentation

- `BACKLOG.md` — single source of truth for all "未解决 / 未处理 / 后续规划" items (清理重构 + 跳过的 P0/P1 + 中/低优先级 + 战略方向 + 延期/不做).
- `ROADMAP.md` — strategic direction (R11+) + historical record of R10.5.x releases.
- `docs/ARCHITECTURE.md` — backend architecture.
- `docs/DEPLOYMENT.md` — deployment (systemd, Docker Compose, K8s).
- `docs/ADR/0001-0003.md` — architectural decision records.
- `.claude/skills/impeccable/` — the [pbakaus/impeccable](https://github.com/pbakaus/impeccable) design skill, installed locally for `/impeccable craft / shape / critique / audit / polish` commands.

## License

MIT. See `LICENSE`.

## Author

qianbkk — [github.com/qianbkk/ScholarFlow](https://github.com/qianbkk/ScholarFlow)