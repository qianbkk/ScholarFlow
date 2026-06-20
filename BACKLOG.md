# ScholarFlow Cleanup BACKLOG

> **唯一跟踪文件**: 任何"未解决 / 未处理 / 后续规划"的项目内清理项都放这里。
> **规则**: 不在 TODO.md / ROADMAP.md / 代码注释 / ADR 重复记录这些项。
> 若有新增,直接 PR 这一文件即可。

---

## 来源

本文件从 2026-06-19 项目全面审查报告迁移,涵盖清理分析的 **C 类 (中期重构)** + **D 类 (版本漂移)** 项。
A 类 (立即删除) 和 B 类 (短期重构) 已在新提交中执行完毕,不再列入。

---

## 📋 C — 中期重构 (Mid-Term Refactor)

> 跨多 PR 工作,需要配套 e2e / 集成测试验证。

### C-001. v4 三 searcher client 抽 `_base.py` (~210 行 dup)

- **现状**: `backend/api/arxiv.py`, `crossref.py`, `pubmed.py` 各自有 `_get_client`/`close_client`/`_mock_fallback`/`_DISABLE_POOL` 模板代码,跟 `semantic_scholar.py`/`openalex.py` 高度重复。
- **目标**: 抽 `backend/api/_base.py` 共享 httpx.AsyncClient 单例 + mock fallback pattern,3 个新 searcher 改为 ~50 行 wrapper。
- **工作量**: 1 天
- **风险**: 中(e2e 测试需要重跑,跨 worker 部署需 smoke test)
- **来源**: TODO.md #6 (R10.5.40 review)

### C-002. `NodeServices` DI 渐进式迁移决策

- **现状**: R10.5 P1-1 立的 `backend/agents/services.py` 73 行 DI 容器,只有 `synthesis_agent.py` 使用,其他 7 个 agent 仍直接 import `call_llm`。
- **目标二选一**:
  1. 全面迁移 8 个 agent 节点到 `NodeServices.llm`,删 fallback 兼容 (1 天 + 大量测试调整)
  2. 全部回滚到旧风格,删 `services.py` 整文件 (半天,推荐)
- **工作量**: 半天到 1 天
- **风险**: 中 (影响全部 agent 节点测试 mock 模式)
- **来源**: 自分析,清理报告 C1

### C-003. `backend/main.py` 体积拆分为 `app.py` + `lifespan.py`

- **现状**: R10.5.51 `/simplify` 减到 578 行,但仍含 lifespan + 启动期审计 + DB init + 周期性 task spawn + middleware 装配 + router 挂载,职责过重。
- **目标**:
  - `backend/app.py`: FastAPI factory + middleware + router 挂载 (~150 行)
  - `backend/lifespan.py`: 启动 / 关闭钩子 (~250 行)
  - `backend/main.py`: 仅 `if __name__ == "__main__": uvicorn.run(...)` (~10 行)
- **工作量**: 半天
- **风险**: 低 (静态测试 `test_routes_not_double_mounted.py` 等需重跑)
- **来源**: 自分析

### C-004. 🔒 `.env` 提交真实 API key 的安全治理

- **现状**: `.env` 包含 MiniMax 真实 API key (前 60 字符 sk-cp-4nFWmy...) 入仓。OPEN_MODE=true 模式下 dev-user 共享 key 是历史妥协,但生产代码 deploy 时仍会拉这个 `.env`,存在 **key 泄露**风险。
- **目标**:
  1. 短期: README 加红色警告 + 在 .gitignore 加 `.env` 兜底
  2. 中期: `git filter-branch` 重写历史,删除 `.env` 历史
  3. 长期: pre-commit hook 阻断 `.env` 变更,要求用 `.env.example` 模板 + 文档指导
- **工作量**: 半天
- **风险**: 高 (涉及 git history rewrite + 影响所有协作者)
- **来源**: 自分析,清理报告 D5

### C-005. R10.5.x 注释爆炸问题 (250+ 处)

- **现状**: grep `R10.5` 在 backend/frontend 代码注释中出现 **250+ 次**。多数是设计动机注释(有价值),但 30% 是已修 bug 的历史注释,长期会让 git blame 失效。
- **目标**: 每 5 个 release 做一次注释归档: 只保留"why",删除"what" + "when" (后者去 CHANGELOG)。
- **工作量**: 半天到 1 天 (每个 PR 顺手精简)
- **风险**: 0 (纯注释,git blame 已记录历史)
- **来源**: 自分析,清理报告 D4

---

## 📋 D — 版本漂移 (Version Drift)

> 文档/注释跟实际代码状态不一致,需要单独 PR 更新。

### D-001. `ROADMAP.md` 头部版本号过期

- **现状**:
  - 头部写 `**当前 HEAD**: 43851f9 (R10.5.40)`
  - 实际 HEAD 是 `499c6d1 (R10.5.51)`
  - 头部写 `**测试基线**: 588 passed`
  - 实际是 648 passed
- **目标**: 改头部为 R10.5.51 + 648 passed + 修复 §0 章节的 R10.5.36..40 → R10.5.36..51。
- **工作量**: 5 分钟
- **风险**: 0
- **来源**: 自分析,清理报告 D1

### D-002. `TODO.md` R10.5.41 candidates 章节过期

- **现状**: TODO.md 顶部 "🔴 High priority (R10.5.41 candidates, 1 week)" 章节建议 4 个 commit (R10.5.41a/b/c/d) 全部未做,实际跳过 R10.5.41 直接到 R10.5.51。
- **目标**: 整个 TODO.md 文件已迁移进 BACKLOG.md (见 E/F/G/H/I 节),文件本身删除。
- **工作量**: 0 (本次合并完成)
- **风险**: 0
- **状态**: ✅ 已完成 (2026-06-20, 跟 E/F/G/H/I 节一起整体合并)

### D-003. `.claude/memory/` 缺少 R10.5.50/51 沉淀

- **现状**:
  - 项目内 `MEMORY.md` 索引的 3 个文件覆盖 R10.5.43-49
  - 项目已到 R10.5.51,新提交的 R10.5.50 + R10.5.51 没沉淀到项目内 memory
  - 全局 memory (在 `~/.claude/projects/`) 已经有 R10.5.43-49 总结,但各自独立
- **目标**:
  1. 在项目内 memory 加 `r10_5_50_51_summary.md`,简记 R10.5.50 (synthesize placeholder 5 篇) + R10.5.51 (8 项 /simplify cleanup)
  2. 更新 `MEMORY.md` 索引
- **工作量**: 20 分钟
- **风险**: 0
- **来源**: 自分析,清理报告 D3

### D-004. `pytest.ini` 悬挂引用 COVERAGE.md

- **现状**: `pytest.ini:18` 注释 "See COVERAGE.md for the baseline number",但 COVERAGE.md 已在 R10.5.41 删除 (见 ROADMAP.md §1)。
- **目标**: 删 `pytest.ini:18` 的 COVERAGE.md 引用注释。
- **工作量**: 1 分钟
- **风险**: 0
- **来源**: 自分析,清理报告 C3
- **状态**: ✅ 已完成 (2026-06-20)

### D-005. `frontend/src/hooks/useSearch.ts` SSEEvent 类型重复

- **现状**: line 80 定义 `type SSEEvent` (union of 6 case),line 84-95 又定义 `interface NodeEvent`(导出) — 两个接口几乎一模一样只是 `status: 'completed'` vs `event: 'node_complete'`。
- **目标**: 删 `SSEEvent` 的 union,统一用 `NodeEvent` + discriminated union type guards,或合并到一个清晰的 type。
- **工作量**: 30 分钟
- **风险**: 低
- **来源**: 自分析,清理报告 D6

### D-006. `backend/main.py` 顶层 `sys.modules[__name__].__class__ = _ScholarFlowMainModule` hack

- **现状**: 已在本批 A 类清理中删除 `_ScholarFlowMainModule` 类 + sys.modules hack,本条目作废。
- **状态**: ✅ 已完成 (2026-06-19)

### D-007. `_RuntimeModeProxy` 注释 / 测试 stub

- **现状**: 已在本批 A 类清理中删除 proxy + 改 3 处测试,本条目作废。
- **状态**: ✅ 已完成 (2026-06-19)

### D-008. `backend/utils/semantic_cache.py` 占位桩

- **现状**: 已在本批 A 类清理中删除整文件 + 改 main.py 引用,本条目作废。
- **状态**: ✅ 已完成 (2026-06-19)

---

## 🔴 E — 跳过的 R10.5.x P0/P1 (TODO.md #1-7 继承)

> 原 TODO.md "🔴 High priority (R10.5.41 candidates)" 章节 7 项,实际跳过 R10.5.41 直接到 R10.5.51。
> 仍然未做,继续追踪。

### E-001. P1-1 静态 guard 60+ 真行为化 (R11 LangGraph 1.0 升级前置)

- **来源**: ROADMAP §1 + TODO.md #1
- **现状**: `backend/main.py` 仍有 60+ 个静态 guard (e.g. `if hasattr(x, y)` / `if x is not None`),R10.5.30 修过一批但还有 ~60 个存活。R11 LangGraph 1.0 升级要重构 `backend/main.py`,静态 guard 会让重构卡住。
- **目标**: 真行为化 (e.g. 失败抛明确异常、缺失字段 → 立即报错) + 删 guard。
- **工作量**: 1-2 天
- **风险**: 中 (Locks `backend/main.py` refactor freedom)
- **阻塞**: R11 升级

### E-002. P2-10 SSE 后端 is_disconnected 检测

- **来源**: TODO.md #2
- **现状**: 客户端断开连接时,SSE 后端还在跑完整 graph,浪费 LLM token + 计算。
- **目标**: 在 graph 主循环里检测 `request.is_disconnected()`,断开时立即终止。
- **工作量**: 1h (1-line fix in `backend/api/routes/search.py`)
- **风险**: 低

### E-003. Phase 3 — Unpaywall + pdfplumber PDF 全文 (evidence_extractor)

- **来源**: R10.5.37 user directive + TODO.md #3
- **现状**: 用户在 R10.5.37 "all phases" 中点过 Phase 3 (拉 PDF 全文喂 evidence_extractor),但只做了 abstract extraction,Phase 3 没交付。
- **目标**: 接入 Unpaywall API (免费版) + pdfplumber 解析 PDF 全文,作为 evidence_extractor 的输入。
- **工作量**: 半天
- **风险**: 中 (新外部 API 依赖)

### E-004. v4 `is_degraded` UI badge 恢复 (R10.5.40 review #3)

- **来源**: R10.5.40 5-agent review + TODO.md #4
- **现状**: `newversion/frontend/src/types/index.ts` 的 `SearchStatus` 声明了 `is_degraded?: boolean`,但 v4 UI 没读它显示 badge。真实 bug trace — 降级模式用户看不到。
- **目标**: 在 v4 header 加 degradation badge (红色/黄色),从 `is_degraded` 字段取状态。
- **工作量**: 30 行
- **风险**: 低

### E-005. 删 `ReportView.tsx` 死代码 (R10.5.40 review #5)

- **来源**: R10.5.40 5-agent review + TODO.md #5
- **现状**: `ReportView.tsx` 有 useEffect + 空 div,跟主 render path 重复 marked.parse,2× markdown parse perf。
- **目标**: 删死 useEffect + 验证主 path 渲染。
- **工作量**: 1 行删 + 测试
- **风险**: 极低

### E-006. ⚙️ 3 个 v4 SSE 回调接 UI (R10.5.40 review)

- **来源**: R10.5.40 5-agent review + TODO.md #7
- **现状**: R10.5.51 cleanup 把 v4 `EmptyState.tsx` 的 4 个 SSE 回调改成 `console.debug`(原本是 `() => undefined` 占位)。等于 live log / paper stream 没接 UI。
- **目标**: 在 v4 加 `LiveLogPanel` + `PaperStreamChip` 组件,onLog/onPapers/onRanked/onCritique 真正渲染。
- **工作量**: 1h
- **风险**: 低

---

## 🟡 F — 中优先级战略 (P3-1..11 + SKIP-6..9, TODO.md #8-22 继承)

> 按"使用场景触发"分组。不是常驻项,有触发再做。

### 文档 / 发布 (P3-1..5)

#### F-001. P3-1 SECURITY.md 单独文件

- **触发**: 对外发布 + 接受 PR
- **工作量**: 1h

#### F-002. P3-2 API 文档自动生成 (SSE event schema)

- **触发**: 对外 API 发布
- **工作量**: 30m

#### F-003. P3-3 SBOM (`pip-licenses` / `syft`)

- **触发**: 企业合规
- **工作量**: 1h

#### F-004. P3-4 国际化 i18n (i18next 中英双语)

- **触发**: 海外用户 (R16)
- **工作量**: 半天

#### F-005. P3-5 requirements.txt 上界收窄 + dev 文件拆分

- **触发**: LTS 维护期
- **工作量**: 持续

### 监控 / 可观测 (P3-6..8)

#### F-006. P3-6 Prometheus 埋点 (节点耗时直方图 / cost 分布 / cache hit rate)

- **触发**: 真实生产
- **工作量**: 1 天

#### F-007. P3-7 OpenTelemetry trace (LLM/API/DB 调用)

- **触发**: 多服务架构
- **工作量**: 半天

#### F-008. P3-8 结构化 JSON 日志 (JsonFormatter)

- **触发**: ELK / Grafana / Loki
- **工作量**: 20 行

### 性能 / 架构 (P3-9..11)

#### F-009. P3-9 多 worker 预算原子性 (SQLite → Redis INCR/DECR)

- **触发**: K8s 多实例 (R15)
- **工作量**: 1 周
- **风险**: 中 (涉及 R10.5.43 的 SQLite 方案回滚)

#### F-010. P3-10 代理探测改 async (0.25s 阻塞冷启动)

- **现状**: `backend/api/routes/admin.py` 的代理探测 sync 阻塞 ~0.25s。
- **目标**: 改 `httpx.AsyncClient` 异步探测,不阻塞 startup。
- **工作量**: 15 行
- **风险**: 低

#### F-011. P3-11 mock synthesis regex 改 LLM JSON (消除 `**[Paper i]**` 脆弱)

- **现状**: `**[Paper i]**` placeholder regex 偶尔遗漏真实数据。
- **目标**: mock synthesis 走 LLM JSON 输出。
- **工作量**: 1h

### 测试覆盖 (SKIP-6, SKIP-7)

#### F-012. SKIP-6 7 个 agent 节点单测 (R10.5.33 留 critic + query_decomposer 共 10 case, 剩 7 节点)

- **触发**: agent 节点拆分/重构
- **工作量**: 1 天

#### F-013. SKIP-7 前端 Vitest/Jest 测试

- **现状**: UI 测试价值在 D3 (Playwright),Vitest 成本/价值比低。
- **工作量**: 半天

### 集成 (SKIP-8, SKIP-9)

#### F-014. SKIP-8 Python SDK (Zotero 集成)

- **触发**: Zotero/Mendeley 集成目标
- **工作量**: 3 天

#### F-015. SKIP-9 Webhook 模式 `POST /search {callback_url}`

- **触发**: 移动端 / 批处理
- **工作量**: 1 天

---

## 🟢 G — 低优先级边界 (SKIP-1..5/10, TODO.md #23-28 继承)

> 调试/边界/mock 细节。极少触发。

| 编号 | 标题 | 来源 | 说明 |
|---|---|---|---|
| G-001 | SKIP-1 `_DISABLE_HTTP_POOL` 调试模式连接泄漏 | TODO.md #23 | Debug-only |
| G-002 | SKIP-2 Mock 中文论文 URL 404 (GitHub 链接) | TODO.md #24 | 已知边界 |
| G-003 | SKIP-3 Mock 数据 `openalex_W003` 与 `ss_041_gan` 重复 | TODO.md #25 | Auto-deduped |
| G-004 | SKIP-4 Mock 中文 token 估算偏低 | TODO.md #26 | mock 模式 $0 |
| G-005 | SKIP-5 `doi` 字段 TS 类型 (当前 `url` 覆盖) | TODO.md #27 | 加 BibTeX export 时做 |
| G-006 | SKIP-10 Mock 模式 UI 徽标 | TODO.md #28 | Demo mode visual |

---

## ⏸ H — 延期 (触发型, TODO.md #29-30 继承)

| 编号 | 标题 | 阻塞条件 | 恢复条件 |
|---|---|---|---|
| H-001 | COVERAGE.md 真实 baseline 数字 | `pip install pytest-cov` blocked (offline env) | 在线环境跑 `pytest --cov=backend` |
| H-002 | v4 (`newversion/`) → v1 迁移评估 | v4 留作 design exploration, 不强制迁移 | 等用户决定哪边胜出 |

---

## 🚫 I — 明确不做 (TODO.md "Explicitly not doing" 继承)

| 编号 | 标题 | 原因 |
|---|---|---|
| I-001 | Google Scholar integration (`scholarly` lib) | Violates Google ToS; Agent 1 deliberately skipped |
| I-002 | Restore v3 design (R10.5.37) | Superseded by v4 (R10.5.38); v3 frontend deleted in R10.5.38 |
| I-003 | Restore v2 design (R10.5.36) | User said v2 too similar to v1, deleted in R10.5.37 |
| I-004 | Re-add `eval/`, `test_run.py` | Old R10.5.16 eval scripts; user said "test scripts don't push" |

---

## 🛣 R — R11+ 战略方向 (ROADMAP.md §2 继承)

> 大版本规划,有触发 (E 类前置 / 用户需求 / 业务时机) 才启动。

### R-011. R11 — LangGraph 1.0 升级 (Phase 2 启动)

- **触发**: langgraph 1.0 是破坏性 API 变更
- **范围**: API 迁移 / Checkpoint 续传升级 / 节点 dict→dict 抽象
- **前置**: E-001 (P1-1 静态 guard 真行为化)
- **成本**: 2-3 天
- **关联代码**: `backend/main.py:77` (真实语义缓存留 R11+), `backend/utils/cache.py:47` (真实 embedding), `backend/utils/session_store.py:124` (session 滑动过期完善), `backend/api/routes/search.py:330,371` (last_event_id 真续传)

### R-012. R12 — Memory Layer

- Vector DB (FAISS / Chroma) 长期记忆
- Episodic memory + Semantic retrieval
- **成本**: 1-2 周
- **关联代码**: `backend/utils/cache.py` (FAISS 集成占位), `backend/utils/circuit_breaker.py:22` (排期 R11+, 应迁 R12)

### R-013. R13 — Multi-Agent Runtime

- Planner / Executor / Reflector / Router 完整控制流
- Tool routing + tool ACL
- **进度**: R10.5.32 F7 (summarize/critique 端点) 是第一步
- **成本**: 2-4 周

### R-014. R14 — Sandbox

- Docker sandbox 执行 LLM-generated code
- Syscall isolation + resource limits + timeout enforcement
- **成本**: 1-2 周

### R-015. R15 — K8s 企业级部署

- Redis 预算原子性 + SSE is_disconnected + Prometheus + OpenTelemetry + SBOM + 结构化日志
- **聚合**: E-002 + F-006 + F-007 + F-008 + F-009 + F-003
- **成本**: 1-2 周

### R-016. R16 — 海外用户

- i18n 中英双语 + 移动端响应式 + STORM / PaperQA2 竞品对标 + 多检索器插件
- **聚合**: F-004 + 移动端相关项
- **成本**: 2-4 周

---

## 📚 附录:代码注释中"待办"指针的来源映射

> 下列代码注释里的 R11+ / P1-1 / P3-* 字样属于"未来做"语义,统一以本 BACKLOG.md 为准。
> 不要在代码注释里再立新条目,新条目加在本文件。

| 注释位置 | 内容 | 对应 BACKLOG 编号 |
|---|---|---|
| `backend/main.py:77` | 真实语义缓存留 R11+ | R-011 |
| `backend/main.py:223` | REQUIRE_PASSWORDLESS_LOGIN R11+ 移除 | E-001 / R-011 |
| `backend/main.py:235,238` | X-API-Key header R11+ 移除 EventSource 兼容 | R-011 |
| `backend/config.py:63` | `_getenv_ci` R11+ 计划 | R-011 |
| `backend/utils/cache.py:47,225` | 真实 embedding 留 R11 | R-011 |
| `backend/utils/cache.py:77` | PostgreSQL 跨实例 R11+ | R-015 |
| `backend/auth/dependencies.py:372` | OTP 邮件验证 R11+ | R-013 |
| `backend/agents/graph_builder.py:124` | 开放 expanded 节点 R11+ | R-013 |
| `backend/utils/circuit_breaker.py:22` | 排期 R11+ | (应迁 R-012,见 R-012 备注) |
| `backend/utils/network.py:11` | R11+ 清理 | R-011 |
| `backend/api/routes/admin.py:15` | Redis R11+ | R-015 |
| `backend/agents/synthesis_agent.py:284` | grounding R11+ | R-013 |
| `backend/api/routes/auth.py:85,255,426` | 多 worker bucket / sliding expire / EventSource R11+ | R-011 / R-015 |
| `backend/agents/_schemas.py:15` | Instructor R11+ 多 provider | R-013 |
| `backend/api/routes/models.py:67` | Checkpoint 反序列化 R11+ | R-011 |
| `backend/api/routes/search.py:148,330,364,371` | last_event_id 真续传 R11+ | R-011 |
| `backend/utils/session_store.py:124` | sliding expire R11+ | R-011 |
| `backend/utils/token_estimator.py:23,69` | provider tokenizer / pricing R11+ | R-011 |
| `backend/requirements.txt:11` | numpy 留 R11 embedding 用 | R-011 |
| `frontend/src/services/api.ts:24` | HttpOnly cookie + CSRF R11+ | R-011 |
| `frontend/src/types/index.ts:43` | PageRank R11 NetworkX | R-011 |
| `frontend/src/components/LoginDialog.tsx:282` | HttpOnly+SameSite cookie R11+ | R-011 |
| `frontend/src/components/GraphPanel.tsx:14` | MAX_FRONTEND_NODES 防御 R11+ | R-011 |
| `frontend/src/hooks/useSearch.ts:294` | SSE 续传 R11+ checkpointer | R-011 |
| `backend/agents/services.py:2,4,32` | DI 渐进式 (AAA.txt P1-1) | C-002 |
| `backend/agents/synthesis_agent.py:49` | services 可选参数 P1-1 | C-002 |
| `backend/api/openalex.py:75,140` | D4 P1-1 | C-002 |
| `backend/utils/audit_log.py:2,17,119` | P1-12 审计 | (已合并进 E-001 系列) |
| `backend/__init__.py:2` | P3-11 fix | F-011 |
| `frontend/src/components/ChangelogModal.tsx:95` | D4 P1-1 changelog tag | (历史记录) |
| `frontend/src/hooks/useSearch.ts:568` | P1-11 假进度计时器 | (R10.5 已修,历史注释) |
| `newversion/frontend/src/ui/EmptyState.tsx:50` | C-006 SSE 回调占位 | E-006 |

---

## 📌 操作规则

1. **新增项**: 直接 PR 本文件,格式 `### XX-XXX. 标题` (XX 为分类前缀,见下表)。
2. **完成项**: 移到对应分类末尾的"已废弃"区,标记 `✅ 已完成 (日期)`,下个 release 周期清理。
3. **优先级**: 本文件 C/D 类是清理/重构项,用 `工作量` + `风险` 维度;E/F/G 类是功能待办,保留原 P0/P1/P2/P3 标签 (从 TODO.md 继承)。
4. **本文件 scope**: 全部"未解决 / 未处理 / 后续规划"项统一在此 — 包括清理重构、版本漂移、功能待办、战略方向、延期/跳过。**禁止** 在 TODO.md / ROADMAP.md / 代码注释 / ADR 重复记录。

### 分类索引

| 前缀 | 类别 | 来源 | 内容 |
|---|---|---|---|
| C | 中期重构 | 自分析 | 跨多 PR 工作 (e.g. main.py 拆分、searcher 抽 base) |
| D | 版本漂移 | 自分析 | 文档/注释跟代码状态不一致 |
| E | 跳过的 R10.5.x P0/P1 | TODO.md #1-7 | 立项了但 R10.5.41 跳过直接到 R10.5.51 |
| F | 中优先级战略 (P3-1..11) | TODO.md #8-22 | 文档/monitoring/perf/test/集成 |
| G | 低优先级边界 (SKIP-1..5/10) | TODO.md #23-28 | 调试/边界/mock 细节 |
| H | 延期 (触发型) | TODO.md #29-30 | 等环境/触发 |
| I | 明确不做 | TODO.md "Explicitly not doing" | ToS / 用户否决 |
| R | R11+ 战略方向 | ROADMAP.md §2 | 大版本规划 (R11 LangGraph / R12 Memory / ...) |