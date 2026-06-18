# ScholarFlow — Pending Work

> Single source of truth for everything not yet done. Anything not in
> `ROADMAP.md` (strategic direction) or this file is "done or skipped".
>
> Last update: 2026-06-18 (after R10.5.40 5-agent mega-refactor)

## 🔴 High priority (R10.5.41 candidates, 1 week)

| # | Item | Source | Cost | Blocking |
|---|------|--------|------|----------|
| 1 | **P1-1 静态 guard 60+ 真行为化** (R11 LangGraph 1.0 升级前置) | ROADMAP §1 | 1-2 天 | Locks `backend/main.py` refactor freedom |
| 2 | **P2-10 SSE 后端 is_disconnected 检测** | ROADMAP §2 | 1h | Client disconnect still runs full graph (waste) |
| 3 | **Phase 3 — Unpaywall + pdfplumber PDF 全文** (extracted abstract → fulltext for evidence_extractor) | R10.5.37 user directive | 半天 | Was in user-requested "all phases" but not delivered |
| 4 | **R10.5.40_REVIEW #3** 恢复 v4 `is_degraded` UI badge (type declares it, no UI reads it) | R10.5.40 review | 30 行 | Real bug trace |
| 5 | **R10.5.40_REVIEW #5** 删 `ReportView.tsx` 死代码 (useEffect + 空 div, repeats marked.parse 2×) | R10.5.40 review | 1 行删 | 2× markdown parse perf + readability |
| 6 | **R10.5.40_REVIEW #6** 3 个新 searcher client 抽 `backend/api/_base.py` (~210 行 dup) | R10.5.40 review | 半天 | Real reuse opportunity |
| 7 | **R10.5.40_REVIEW** 3 个 v4 SSE 回调是 `() => undefined` 死代码 (live log 没接 UI) | R10.5.40 review | 1h | Half-finished wiring |

## 🟡 Medium priority (triggered by use case)

### Documentation & publishing (P3-1..5)
| # | Item | Cost | Trigger |
|---|------|------|---------|
| 8 | P3-1 SECURITY.md 单独文件 | 1h | External publish + accept PRs |
| 9 | P3-2 API 文档自动生成 (SSE event schema 描述) | 30m | External API publish |
| 10 | P3-3 SBOM (`pip-licenses` / `syft`) | 1h | Enterprise compliance |
| 11 | P3-4 国际化 i18n (i18next 中英双语) | 半天 | Overseas users (R16) |
| 12 | P3-5 requirements.txt 上界收窄 + dev 文件拆分 | 持续 | LTS maintenance |

### Monitoring / observability (P3-6..8)
| # | Item | Cost | Trigger |
|---|------|------|---------|
| 13 | P3-6 Prometheus 埋点 (node 耗时直方图 / cost 分布 / cache hit rate) | 1 天 | Real production |
| 14 | P3-7 OpenTelemetry trace (LLM/API/DB 调用) | 半天 | Multi-service architecture |
| 15 | P3-8 结构化 JSON 日志 (JsonFormatter) | 20 行 | ELK / Grafana / Loki |

### Performance / architecture (P3-9..11)
| # | Item | Cost | Trigger |
|---|------|------|---------|
| 16 | P3-9 多 worker 预算原子性 (SQLite → Redis INCR/DECR) | 1 周 | K8s multi-instance |
| 17 | P3-10 代理探测改 async (0.25s 阻塞冷启动) | 15 行 | Cold-start perceived lag |
| 18 | P3-11 mock synthesis regex 改 LLM JSON (消除 `**[Paper i]**` 脆弱) | 1h | Mock report occasionally missing data |

### Test coverage (SKIP-6, SKIP-7)
| # | Item | Cost | Trigger |
|---|------|------|---------|
| 19 | SKIP-6 7 个 agent 节点单测 (R10.5.33 留 critic+query_decomposer 共 10 case, 剩 7 节点) | 1 天 | Agent node split / refactor |
| 20 | SKIP-7 前端 Vitest/Jest 测试 (UI 价值在 D3) | 半天 | CI Playwright slow |

### Integrations (SKIP-8, SKIP-9)
| # | Item | Cost | Trigger |
|---|------|------|---------|
| 21 | SKIP-8 Python SDK (Zotero 集成) | 3 天 | Zotero/Mendeley integration target |
| 22 | SKIP-9 Webhook 模式 `POST /search {callback_url}` | 1 天 | Mobile / batch scenarios |

## 🟢 Low priority (rarely triggered)

| # | Item | Source | Note |
|---|------|--------|------|
| 23 | SKIP-1 `_DISABLE_HTTP_POOL` 调试模式连接泄漏 | ROADMAP | Debug-only |
| 24 | SKIP-2 Mock 中文论文 URL 404 (GitHub 链接) | ROADMAP | Known boundary |
| 25 | SKIP-3 Mock 数据 `openalex_W003` 与 `ss_041_gan` 重复 | ROADMAP | Auto-deduped |
| 26 | SKIP-4 Mock 中文 token 估算偏低 | ROADMAP | mock 模式 $0 |
| 27 | SKIP-5 `doi` 字段 TS 类型 (当前 `url` 覆盖) | ROADMAP | Add BibTeX export |
| 28 | SKIP-10 Mock 模式 UI 徽标 | ROADMAP | Demo mode visual |

## ⏸ Deferred (waiting on env / trigger)

| # | Item | Blocked by | Resume when |
|---|------|-----------|-------------|
| 29 | COVERAGE.md 真实 baseline 数字 | `pip install pytest-cov` blocked (offline env) | Online env: `pytest --cov=backend` |
| 30 | v4 (`newversion/`) → v1 迁移评估 | v4 留作 design exploration, 不强制迁移 | 等用户决定哪边胜出 |

## 🚫 Explicitly not doing

| Item | Reason |
|------|--------|
| Google Scholar integration (`scholarly` lib) | Violates Google ToS; Agent 1 deliberately skipped |
| Restore v3 design (R10.5.37) | Superseded by v4 (R10.5.38); v3 frontend deleted in R10.5.38 |
| Restore v2 design (R10.5.36) | User said v2 too similar to v1, deleted in R10.5.37 |
| Re-add `eval/`, `test_run.py` | Old R10.5.16 eval scripts; user said "test scripts don't push" |

## Total

- 🔴 High: 7
- 🟡 Medium: 15
- 🟢 Low: 6
- ⏸ Deferred: 2
- 🚫 Skipped: 4
- **Grand total: 34**

## Suggested next commit (R10.5.41)

If you return to the "small commit" rhythm:

- **R10.5.41a** (1h): P2-10 SSE is_disconnected (1-line fix in `backend/api/routes/search.py`)
- **R10.5.41b** (半天): R10.5.40 review fixes #4 + #5 (UI badge + 死代码删, both trivial)
- **R10.5.41c** (半天): R10.5.40 review fix #6 (抽 `backend/api/_base.py` for the 3 searcher clients)
- **R10.5.41d** (1-2 天): P1-1 静态 guard 真行为化 (R11 前置, biggest cost)
