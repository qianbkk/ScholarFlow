# ScholarFlow 后续路线图

> **当前 HEAD**: `e5f0086` (R10.5.34)
> **VERSION**: 1.0.2
> **测试基线**: 543 passed / 1 skipped / 0 failed (10m 28s)
> **CI**: 4/4 job 全绿 (test / security / frontend / docker)
> **最近更新**: 2026-06-18 — R10.5.34 收口

本文件是 ScholarFlow 项目**唯一**的"后续待处理"总览，替代以下已废弃文件：

- ~~`docs/FUTURE_TASKS.md`~~ (R10.5.1 写的 23 条)
- ~~`docs/HANDOFF.md`~~ (R10.5.19 写的 AI 接手清单)
- ~~`docs/COMPREHENSIVE_UPGRADE_REPORT.md`~~ (R10.5.x 升级总报告)
- ~~`docs/UPGRADE_ARCHITECTURE.md`~~ (R10.5.28 holographic 升级报告)

历史记录查 `git log` + `CHANGELOG.md`。新功能加这里，状态改了也改这里。

---

## 0. 总进度

| 类别 | 数量 | R10.5.30-34 已完成 | 剩余 |
|---|---|---|---|
| P0 | 0 | 全部 | 0 |
| P1 | 2 | 1 | 1 |
| P2 | 10 | 9 | 1 |
| P3/DEFER | 15 | 0 | 15 |
| SKIP (触发型) | 12 | 3 | 9 |
| **合计** | **39** | **13 (33%)** | **26** |

R10.5.30-34 三波 (16 commits) 修了：
- P0 全清 (CG.txt §1 全部真修：email=身份 / admin 后门 / 多 worker / localStorage XSS / main.py 1115 行腐化)
- P1-2 (marked 异步化)
- 9/10 P2 (F4 4-Context / F5 CommandPalette / F6 migration / F7 agent endpoint / D3 颜色 / cache GC / /health / 优雅 shutdown / 9 skip 解锁)
- 3/12 SKIP (CI 4 job / Docker / 之前的 DONE 项)
- CD.txt §3.1 (agent 单测) 部分缓解：10 case

---

## 1. P1 — 近期必做 (1 项)

### P1-1 静态 guard 60+ 真行为化
- **位置**: `tests/test_budget_lifecycle.py`, `tests/test_cors_hardening.py`, `tests/test_sse_disconnect_budget.py`, `tests/test_router.py`, `tests/test_request_id_propagation.py`
- **现状**: R10.5.30 D2 拆解后大部分被 R10.5.32 P0-1a 解锁 (9 skip → 0 skip)，但 `assert "xxx" in src` 静态扫描模式仍散布在多个 test 文件
- **问题**: 锁死 main.py 重构自由（"为满足静态 guard 而保留内联路由"），R11 LangGraph 1.0 升级前必须清掉
- **完成定义**:
  1. 所有 `assert "xxx" in src` 改写为真实行为测试
  2. `backend/main.py` 头部注释删除 "kept inline to satisfy static test guards" 段
  3. `app.include_router(search_router)` 接替内联路由
- **成本**: 1-2 天
- **风险**: 高 — 重构可能引发回归，需全程测试守护
- **来源**: HANDOFF.md §2.1, R10.5.19 P.txt #5 (R10.5.32 P0-1a 部分缓解)

---

## 2. P2 — 触发型 + 部分已修 (1 项剩余)

### P2-10 SSE 后端 is_disconnected 检测
- **位置**: `backend/api/routes/search.py` event_generator (SSE 段)
- **场景**: 客户端断开 → 后端仍跑完整个 graph (浪费 cost)
- **修复**: 加 `if await request.is_disconnected(): break` 检查
- **成本**: 1 小时
- **来源**: HANDOFF.md §5.1 (R10.5.19 X1 修了前端，后端待补)

### 已修 P2 (9 项)
| 项 | 完成于 |
|---|---|
| D3 force simulation O(N²) tick (alphaDecay 0.05→0.08) | R10.5.32 wave 6 |
| Cache GC (search_cache >30d/1000rows LRU) | R10.5.32 wave 6 |
| D3 颜色区分度 (Viridis 色觉障碍友好) | R10.5.32 wave 6 |
| /health version 联动 VERSION 文件 | R10.5.32 wave 7 |
| 优雅 shutdown (lifespan 等 in-flight 30s + cache GC) | R10.5.32 wave 7 |
| DB migration 框架 (apply_migration + _schema_migrations) | R10.5.31 F6 |
| /agents/summarize + /critique endpoint (F5 stub 转真) | R10.5.32 F7 |
| CommandPalette 13 命令接真 handler (11 真 + 2 stub → R10.5.32 F7 全真) | R10.5.31 F5 |
| 9 agent 节点 0 单测 → 10 (CD.txt §3.1 缓解) | R10.5.33 |

---

## 3. P3 / DEFER — 中长期 (15 项)

### 文档/治理 (5)
| # | 项 | 成本 | 触发 |
|---|---|---|---|
| P3-1 | LICENSE / CONTRIBUTING / SECURITY.md 单独文件 | 1h | 对外发布 + 接受 PR |
| P3-2 | API 文档自动生成 (`/search/stream` SSE 事件 schema 描述) | 30m | 对外发布 API |
| P3-3 | SBOM 软件物料清单 (`pip-licenses` / `syft`) | 1h | 企业合规审查 |
| P3-4 | 国际化 i18n (i18next 中英双语) | 半天 | 海外用户 |
| P3-5 | requirements.txt 上界收窄 + dev 文件 | 持续 | 项目进 LTS |

### 监控/可观测性 (3)
| # | 项 | 成本 | 触发 |
|---|---|---|---|
| P3-6 | /search Prometheus 埋点 (node 耗时直方图 / cost 分布 / cache hit rate) | 1 天 | 真上生产 |
| P3-7 | OpenTelemetry trace (LLM/API/DB 调用) | 半天 | 多服务架构 |
| P3-8 | 结构化 JSON 日志 (JsonFormatter) | 20 行 | 接 ELK / Grafana / Loki |

### 性能/架构 (3)
| # | 项 | 成本 | 触发 |
|---|---|---|---|
| P3-9 | 多 worker 预算原子性 (SQLite → Redis INCR/DECR) | 1 周 | K8s 多实例 |
| P3-10 | 代理探测改 async (避免冷启动 0.25s 阻塞) | 15 行 | 冷启动感知卡顿 |
| P3-11 | mock synthesis regex 改 LLM JSON (消除 `**[Paper i]**` 正则脆弱) | 1h | mock 报告偶尔漏数据 |

### 工程债 (2)
| # | 项 | 成本 | 触发 |
|---|---|---|---|
| P3-12 | 静态 guard 60+ 真行为化 (同 P1-1) | 1-2 天 | R11 前置 |
| P3-13 | 多 worker Semaphore + cache_key 漏 mode (K8s 部署时) | 1 天 | K8s 部署 |

### 触发型 (2)
| # | 项 | 成本 | 触发 |
|---|---|---|---|
| P3-14 | 移动端响应式 (768px 以下折叠布局) | 50 行 | 定位改为通用工具 |
| P3-15 | QueryPanel 100+ 论文虚拟化 (`react-window`) | 20 行 | 返 Top 100+ 论文 |

---

## 4. SKIP — 触发型不做 (9 项剩余)

| # | 项 | 成本 | 触发 |
|---|---|---|---|
| SKIP-1 | `_DISABLE_HTTP_POOL` 模式连接泄漏 | 20 行 | 调试模式专用 |
| SKIP-2 | Mock 中文论文 URL 404 (GitHub 链接,已知边界) | 5 行 | 用户在 mock 点链接 404 |
| SKIP-3 | Mock 数据 `openalex_W003` 与 `ss_041_gan` 重复 (自动去重) | 5 行 | 永远不需要 |
| SKIP-4 | Mock 中文 token 估算偏低 (mock 模式 $0 实际成本) | 10 行 | mock 报告需对外展示精确 token |
| SKIP-5 | `doi` 字段 TS 类型 (当前 `url` 跳转覆盖) | 1 行 | 加导出 BibTeX 时 |
| SKIP-6 | 8 个 Agent 节点单测 (R10.5.33 加了 critic + query_decomposer 共 10 个 case，剩 7 个节点未加) | 1 天 | agent 节点拆分/重构时 |
| SKIP-7 | 前端 Vitest/Jest 测试 (UI 价值在 D3 可视化) | 半天 | 接 CI 跑 Playwright 慢时 |
| SKIP-8 | Python SDK (Zotero 集成) | 3 天 | Zotero/Mendeley 集成目标 |
| SKIP-9 | Webhook 模式 (`POST /search {callback_url}`) | 1 天 | 移动端/批量场景 |
| SKIP-10 | Mock 模式 UI 徽标 | 1h | 演示模式可视化 |

### 已完成 SKIP (3 项)
- SKIP-11 GitHub Actions CI 4 job (R10.5.34 实现并通过)
- SKIP-12 Dockerfile + docker-compose (R8.2 交付)
- SKIP-13 之前的 DONE 项

---

## 5. 后续大版本规划 (R11+ 触发型)

### R11 — LangGraph 1.0 升级 (Phase 2 启动)
- **触发**: langgraph 1.0 是破坏性 API 变更，R10.5.x 还在用 0.6.11
- **范围**:
  - LangGraph 1.0 API 迁移 (R10.5.19 P.txt #5 标 PYSEC-2024-38)
  - LangGraph Checkpoint 续传升级 (R10.5.19 P.txt #5 GHSA-9hjg-9rjm-9j3p)
  - LangGraph 解耦 (节点 dict→dict 抽象，HANDOFF 2.10)
- **前置**: P1-1 静态 guard 行为化必须先做
- **成本**: 2-3 天

### R12 — Memory Layer (CD.txt §5.2 缓解)
- **触发**: 跨 session 记忆需求
- **范围**:
  - Vector DB (FAISS / Chroma) 长期记忆
  - Episodic memory (历史查询 embedding 检索)
  - Semantic retrieval (相似查询推荐)
- **成本**: 1-2 周

### R13 — Multi-Agent Runtime (CD.txt §2.2 完整修复)
- **触发**: 真正 agentic RAG 定位
- **范围**:
  - Planner / Executor / Reflector / Router 完整控制流
  - 动态分支 + 回溯 + retry strategy
  - Tool routing + tool ACL (CD.txt §4.3)
- **进度**: R10.5.32 F7 (`/agents/summarize` + `/agents/critique`) 是第一步
- **成本**: 2-4 周

### R14 — Sandbox (CD.txt §4.2)
- **触发**: 项目支持 code execution / MBPP / HumanEval 风格任务
- **范围**:
  - Docker sandbox 执行 LLM-generated code
  - Syscall isolation + resource limits
  - Timeout enforcement
- **成本**: 1-2 周

### R15 — K8s 企业级部署 (触发型)
- **触发**: 真实生产环境
- **范围** (聚合):
  - P3-9 多 worker 预算原子性 (Redis)
  - P2-10 SSE 后端 is_disconnected (已部分)
  - P3-6 Prometheus 埋点
  - P3-7 OpenTelemetry trace
  - P3-3 SBOM
  - P3-1 LICENSE / CONTRIBUTING / SECURITY.md
  - P3-8 结构化 JSON 日志
- **成本**: 1-2 周 (聚合 P3-6/7/8/22/23 + P3-9 全做)

### R16 — 海外用户
- **触发**: 用户群出海
- **范围** (聚合):
  - P3-4 i18n 中英双语
  - P3-14 移动端响应式
  - STORM / PaperQA2 竞品对标功能 (CG.txt §对标)
  - 多检索器插件 (YouRM / Bing / Tavily / Serper / Brave 等, CG.txt §对标)
- **成本**: 2-4 周

---

## 6. 触发信号 → 应做的项

| 触发信号 | 优先做 |
|---|---|
| 新用户反馈"跑不起来" | P3-1 LICENSE / 已 DONE (CI 4 job) |
| 反馈"手机上没法用" | P3-14 移动端响应式 |
| 反馈"图谱颜色看不清" | DONE (R10.5.32 wave 6 Viridis) |
| mock 报告偶尔内容缺失 | P3-11 mock synthesis JSON |
| 项目进入企业级部署 | R15 (聚合 P3-6/7/8/9/22/23) |
| 接受外部 PR | P1-1 静态 guard + P3-1 LICENSE + SKIP-6 Agent 单测 + SKIP-7 前端测试 |
| 反馈"重复查询太贵" | P3-11 mock synthesis (无关)；改 cache TTL + 加 LLM response cache |
| 项目进入 LTS 维护 | P3-5 requirements 收窄 + P1-1 路由测试加深 |
| 用户群国际化 | R16 (聚合 P3-4 + P3-14) |
| 跨 session 记忆需求 | R12 |
| 真正 agentic RAG 定位 | R13 |
| 支持 code execution 任务 | R14 |

---

## 7. 下一波 R10.5.35 建议

按"小改动攒一波"原则，单 commit + push:

1. **P1-1 静态 guard 60+ 真行为化** (1-2 天) — R11 LangGraph 1.0 升级前必须
2. **P2-10 SSE 后端 is_disconnected** (1h) — 客户端断不再浪费 cost
3. **小 CI 修补** (1h) — 任何 R10.5.34 后发现的 flaky

3 项 1 commit，中等规模。commit+push 后开 R11 大版本。

---

## 8. 审计依据

- **CG.txt** (R10.5.x 审计): P0 #1 email=身份 / P0 #2 admin 后门 / P0/P1 #3 多 worker / P1 #4 localStorage / P1 #5 main.py 腐化 — R10.5.30 D1-D7 全部真修
- **CD.txt** (架构代差审计): §1.1 LangGraph graph (R10.5.x 已用) / §2.2 planner (R10.5.32 F7 迈一步) / §3.1 单测 (R10.5.33 缓解) / §4.1 prompt injection (4 层 XSS 防护) / §5.1 性能 / §5.2 memory (R12) / §7 illusion (R10.5.31 F4 部分缓解) / Phase 2-4 (R12-R14) — 未涉及
- **FUTURE_TASKS.md** (R10.5.1 23 条) — 已废弃，整合到此文件
- **HANDOFF.md** (R10.5.19 14 条) — 已废弃，整合到此文件
- **审计 XYZ.txt** (R10.5.x 14 项) — R10.5 已完成
- **P.txt + Q.txt** (R10.5.19 12 项) — R10.5.19 已完成
