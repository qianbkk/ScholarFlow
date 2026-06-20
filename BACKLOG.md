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
- **目标**: 删整个章节,改成 "🔴 P0 from R10.5.40 review" 重新整理 4 项 review fix。
- **工作量**: 15 分钟
- **风险**: 0
- **来源**: 自分析,清理报告 D2

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

## 📌 操作规则

1. **新增项**: 直接 PR 本文件,格式 `### C-XXX. 标题` 或 `### D-XXX. 标题`。
2. **完成项**: 移到对应分类末尾的"已废弃"区,标记 `✅ 已完成 (日期)`,下个 release 周期清理。
3. **优先级**: 不在本文件标 P0/P1/P2 (那是 TODO.md / ROADMAP.md 的语义);仅用 `工作量` + `风险` 维度。
4. **本文件 scope**: 仅清理 / 重构 / 漂移类项。功能类需求进 `TODO.md`,战略方向进 `ROADMAP.md`。