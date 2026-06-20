# ScholarFlow 后续路线图

> **本文件仅保留战略方向 + 历史记录**。具体的"待办 / 触发型 / 跳过"清单见 [`BACKLOG.md`](BACKLOG.md)。
> 历史记录查 `git log`。
>
> **最近更新**: 2026-06-20 — R10.5.51 cleanup 收口,TODO.md 内容并入 BACKLOG.md

---

## 1. 已废弃的 4 类文档 (历史记录)

- ~~`docs/FUTURE_TASKS.md`~~ (R10.5.1 写的 23 条)
- ~~`docs/HANDOFF.md`~~ (R10.5.19 写的 AI 接手清单)
- ~~`docs/COMPREHENSIVE_UPGRADE_REPORT.md`~~ (R10.5.x 升级总报告)
- ~~`docs/UPGRADE_ARCHITECTURE.md`~~ (R10.5.28 holographic 升级报告)
- ~~`AGENTS_LOCK.md` / `R10_5_40_REVIEW.md` / `COVERAGE.md`~~ (R10.5.40 内部协调文件, R10.5.41 删)
- ~~`eval/` / `test_run.py` / `scholarflow.bat` / 根目录 `scholarflow.py`~~ (R10.5.40 之前的过时脚本, R10.5.41 删)
- ~~`frontend/src-v2/`~~ (R10.5.36 尝试 v2 时建, R10.5.37 删后又留空目录, R10.5.41 清)
- ~~`TODO.md`~~ (R10.5.51 cleanup: 全部 34 项并入 [`BACKLOG.md`](BACKLOG.md) 的 E/F/G/H/I 节)

**唯一保留的跟踪文件**: `BACKLOG.md` (清理/重构/漂移 + 跳过的 P0/P1 + 中/低优先级 + 延期 + 不做 + R11+ 战略) + `ROADMAP.md` (本文件, 战略 + 历史) + `docs/ARCHITECTURE.md` + `docs/DEPLOYMENT.md` + `docs/ADR/0001-0003.md`.

---

## 2. 战略方向 (R11+ 大版本规划)

> 详情 + 前置 + 成本见 `BACKLOG.md` R-011..R-016。

| 版本 | 主题 | 周期 | 触发 |
|---|---|---|---|
| R11 | LangGraph 1.0 升级 + Checkpoint 续传 | 2-3 天 | langgraph 1.0 破坏性变更 |
| R12 | Memory Layer (FAISS + episodic memory) | 1-2 周 | 长期记忆需求 |
| R13 | Multi-Agent Runtime (Planner/Executor/Reflector) | 2-4 周 | 多 agent 控制流 |
| R14 | Sandbox (Docker exec LLM-generated code) | 1-2 周 | 代码生成安全 |
| R15 | K8s 企业级部署 (Redis + Prometheus + SBOM) | 1-2 周 | 多实例 + 合规 |
| R16 | 海外用户 (i18n + 移动端) | 2-4 周 | 国际化 |

R11 前置: BACKLOG.md **E-001** (P1-1 静态 guard 真行为化)。

---

## 3. 审计依据 (历史)

- **CG.txt** (R10.5.x 审计): P0 #1 email=身份 / P0 #2 admin 后门 / P0/P1 #3 多 worker / P1 #4 localStorage / P1 #5 main.py 腐化 — R10.5.30 D1-D7 全部真修
- **CD.txt** (架构代差审计): §1.1 LangGraph graph (R10.5.x 已用) / §2.2 planner (R10.5.32 F7 迈一步) / §3.1 单测 (R10.5.33 缓解) / §4.1 prompt injection (4 层 XSS 防护) / §5.1 性能 / §5.2 memory (R12) / §7 illusion (R10.5.31 F4 部分缓解) / Phase 2-4 (R12-R14) — 未涉及
- **R10.5.36** impeccable 前端 v2 重建 → R10.5.37 删 → R10.5.38 v4 focus-first 重构
- **R10.5.39** 3 多源 (arXiv / Crossref / PubMed) + 12 unit test
- **R10.5.40** 5-agent parallel mega-refactor (Phase 2/4/5 + shared/ + 3 bug fix)
- **R10.5.36..40 指南 24 项**: P1 主题/布局切换 + 内联卡 + 8 节点进度 + shared/ 抽取 + pytest-cov + CONTRIBUTING + 3 ADR + 跨平台 launcher + 图谱 2-hop + EndNote XML + /simplify + /code-review
- **R10.5.41..50** R10.5.41 跳过, R10.5.42..50 散点修复 (CI / 测试污染 / admin store WAL / token pre-check 等), 详见 `git log`。
- **R10.5.51 cleanup** 删 8 项死代码 + STORAGE_KEYS 中央化 + BACKLOG.md 统一跟踪 (本次合并)