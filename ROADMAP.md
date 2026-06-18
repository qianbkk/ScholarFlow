# ScholarFlow 后续路线图

> **当前 HEAD**: `43851f9` (R10.5.40)
> **VERSION**: 1.0.2
> **测试基线**: 588 passed / 1 skipped / 1 failed (10m 37s, R10.5.40)
> **CI**: 4/4 job 全绿 (test / security / frontend / docker)
> **最近更新**: 2026-06-18 — R10.5.40 5-agent mega-refactor 收口

本文件描述 ScholarFlow 项目的**战略方向 + 大版本规划**。
具体的"待办 / 触发型 / 跳过"清单见 [`TODO.md`](TODO.md)。

历史记录查 `git log`。

---

## 0. 总进度

| 类别 | 数量 | R10.5.30-40 已完成 | 剩余 |
|---|---|---|---|
| P0 | 0 | 全部 | 0 |
| P1 | 2 | 1 | 1 |
| P2 | 10 | 9 | 1 |
| P3/DEFER | 15 | 0 | 15 |
| SKIP (触发型) | 12 | 3 | 9 |
| **合计** | **39** | **13 (33%)** | **26** |

R10.5.30-40 五波 (24 commits) 修了:
- R10.5.30 D1-D7 (P0 全清, 7 commits)
- R10.5.31-32 (F1-F7 性能 + 架构, 7 commits)
- R10.5.33 (9 agent 节点 0 单测 → 10, 1 commit)
- R10.5.34-35 (CI 4 job 修 + 文档收口, 3 commits)
- R10.5.36-38 (impeccable 装 + v2/v3/v4 重做, 3 commits)
- R10.5.39-40 (5 多源 + 5-agent 并行 mega, 3 commits)

完整待办见 [`TODO.md`](TODO.md) — 7 项高优先级 + 15 中 + 6 低 + 2 延期 + 4 跳过 = **34 项**.

---

## 1. 已废弃的 4 类文档 (历史记录)

- ~~`docs/FUTURE_TASKS.md`~~ (R10.5.1 写的 23 条)
- ~~`docs/HANDOFF.md`~~ (R10.5.19 写的 AI 接手清单)
- ~~`docs/COMPREHENSIVE_UPGRADE_REPORT.md`~~ (R10.5.x 升级总报告)
- ~~`docs/UPGRADE_ARCHITECTURE.md`~~ (R10.5.28 holographic 升级报告)
- ~~`AGENTS_LOCK.md` / `R10_5_40_REVIEW.md` / `COVERAGE.md`~~ (R10.5.40 内部协调文件, R10.5.41 删)
- ~~`eval/` / `test_run.py` / `scholarflow.bat` / 根目录 `scholarflow.py`~~ (R10.5.40 之前的过时脚本, R10.5.41 删)
- ~~`frontend/src-v2/`~~ (R10.5.36 尝试 v2 时建, R10.5.37 删后又留空目录, R10.5.41 清)

**唯一保留**: `ROADMAP.md` (战略方向) + `TODO.md` (待办清单) + `docs/ARCHITECTURE.md` + `docs/DEPLOYMENT.md` + `docs/ADR/0001-0003.md`.

---

## 2. 战略方向 (R11+ 大版本规划)

### R11 — LangGraph 1.0 升级 (Phase 2 启动)
- **触发**: langgraph 1.0 是破坏性 API 变更
- **范围**: API 迁移 / Checkpoint 续传升级 / 节点 dict→dict 抽象
- **前置**: P1-1 静态 guard 真行为化 (TODO #1)
- **成本**: 2-3 天

### R12 — Memory Layer
- Vector DB (FAISS / Chroma) 长期记忆
- Episodic memory + Semantic retrieval
- **成本**: 1-2 周

### R13 — Multi-Agent Runtime
- Planner / Executor / Reflector / Router 完整控制流
- Tool routing + tool ACL
- 进度: R10.5.32 F7 (summarize/critique 端点) 是第一步
- **成本**: 2-4 周

### R14 — Sandbox
- Docker sandbox 执行 LLM-generated code
- Syscall isolation + resource limits + timeout enforcement
- **成本**: 1-2 周

### R15 — K8s 企业级部署
- Redis 预算原子性 + SSE is_disconnected + Prometheus + OpenTelemetry + SBOM + 结构化日志
- 聚合 TODO #2 + #13 + #14 + #15 + #16 + #10
- **成本**: 1-2 周

### R16 — 海外用户
- i18n 中英双语 + 移动端响应式 + STORM / PaperQA2 竞品对标 + 多检索器插件
- 聚合 TODO #11 + 移动端相关项
- **成本**: 2-4 周

---

## 3. 审计依据

- **CG.txt** (R10.5.x 审计): P0 #1 email=身份 / P0 #2 admin 后门 / P0/P1 #3 多 worker / P1 #4 localStorage / P1 #5 main.py 腐化 — R10.5.30 D1-D7 全部真修
- **CD.txt** (架构代差审计): §1.1 LangGraph graph (R10.5.x 已用) / §2.2 planner (R10.5.32 F7 迈一步) / §3.1 单测 (R10.5.33 缓解) / §4.1 prompt injection (4 层 XSS 防护) / §5.1 性能 / §5.2 memory (R12) / §7 illusion (R10.5.31 F4 部分缓解) / Phase 2-4 (R12-R14) — 未涉及
- **R10.5.36** impeccable 前端 v2 重建 → R10.5.37 删 → R10.5.38 v4 focus-first 重构
- **R10.5.39** 3 多源 (arXiv / Crossref / PubMed) + 12 unit test
- **R10.5.40** 5-agent parallel mega-refactor (Phase 2/4/5 + shared/ + 3 bug fix)
- **R10.5.36..40 指南 24 项**: P1 主题/布局切换 + 内联卡 + 8 节点进度 + shared/ 抽取 + pytest-cov + CONTRIBUTING + 3 ADR + 跨平台 launcher + 图谱 2-hop + EndNote XML + /simplify + /code-review
