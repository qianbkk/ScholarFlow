# R10.5.59 — 5 项前端/后端迭代改进

> 发布日期: 2026-06-21 · Tag: `v10.5.59` · 贡献者: [@qianbkk](https://github.com/qianbkk)
>
> 详细技术报告见 [`RELEASES.md`](https://github.com/qianbkk/ScholarFlow/blob/master/RELEASES.md)

## 🌟 Highlights

- 🍔 **顶部 hamburger Settings** — 删 ⚙ 齿轮按钮,改用左侧 ☰ 三横线唤起 SettingsDrawer;Settings 不再是独立 tab
- 🎚️ **可调论文数量 3-30** — UI 双滑块,默认 5-10;与 budget/iter 并排
- 🎯 **LLM 检索模式严格 ≥ 8 分** — 真实有效文献门槛,iter 不够自动放宽到 ≥ 7,**绝不 mock fallback**;Local 模式允许 mock
- 📄 **Search 概要卡 + Report 居中** — Search tab 不再渲染完整报告,显示标题+Top 5+跳报告按钮;Report tab 内容居中显示
- 🪟 **修复 D3 图谱 hover 颤动 bug** — 主 D3 effect 移除 `hovered` deps,改用 hoveredRef,鼠标滑动节点位置稳定
- 🌐 **完整 i18n 覆盖** — ~180 key 中英双语:TopNav/Search/Report/Graph/History/Settings/Auth/CommandPalette/PipelineProgress 全部走 useT()

## 📦 Changes

### Frontend (R10.5.59)

- `TopNav.tsx`: 删齿轮+加☰+删settings tab
- `QueryInput.tsx`: paperMin/Max 双滑块 (3-30, 默认 5-10)
- `GraphPage.tsx`: 删§4前缀+hoveredRef jitter fix
- `SearchSummary.tsx`: 新建 Search 概要卡 (报告标题+Top 5+跳报告按钮)
- `ReportView.tsx`: 内容居中 (maxWidth 720) + 跳回 Search 按钮
- `SettingsDrawer.tsx`: 删 "midnight 主题天然是夜间模式" 文案
- `i18n/index.ts`: 全面化 (305→483 LOC, ~180 key)
- 清理 3 个死文件: `useSearch.ts` (32KB) + `useLocalStorage.ts` (3.7KB) + `paperFilters.ts` (550B)

### Backend (R10.5.59)

- `models.py`: SearchRequest 加 paperMin/Max; make_initial_state 加 score_threshold/score_relaxed
- `search.py`: SSE + POST 端点透传 paperMin/Max
- `ranker_agent.py`: LLM strict ≥ score_threshold 筛选 + thinking log
- `query_refiner.py`: 触发放宽 8.0→7.0 + score_relaxed 标记

## ✅ Verification

- `npx tsc --noEmit`: **0 errors**
- `npm run build`: 619 modules, 2.14s, index 102.57 kB (gzip 30.01 kB)
- `python -c "from backend.agents.search_agent import search_node"`: OK
- `make_initial_state(runtime_mode='llm')` 返回 `score_threshold=8.0`

## 📚 文档同步

- `README.md`: 全面重写 (Highlights / 3 层架构图 / 8 节点流水线表 / 快捷键表 / 5 版本 release notes)
- `ROADMAP.md`: 加 R10.5.54/55/59 历史
- `BACKLOG.md`: D-005 (useSearch.ts) 标记完成
- `ChangelogModal.tsx`: 加 R10.5.59 + R10.5.55 entries
- `VERSION`: 1.0.6 → R10.5.59
- `package.json`: 1.0.6 → 10.5.59
- `RELEASES.md` (新建): GitHub Releases 草稿区

## 🔗 Links

- 📖 [Documentation](https://github.com/qianbkk/ScholarFlow#readme)
- 🐛 [Report Issues](https://github.com/qianbkk/ScholarFlow/issues)
- 📜 [License: MIT](https://github.com/qianbkk/ScholarFlow/blob/master/LICENSE)
- 🔄 [Previous: R10.5.55](https://github.com/qianbkk/ScholarFlow/releases/tag/v10.5.55) — (若已发布)

---

**Full Changelog**: https://github.com/qianbkk/ScholarFlow/compare/v10.5.55...v10.5.59