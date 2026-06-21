# ScholarFlow Releases

> GitHub Releases 草稿区。`git tag` 后 copy-paste 到 GitHub Releases 页面发布。

---

## R10.5.59 — 2026-06-21

**5 项前端/后端迭代改进 + 完整 i18n**

### 🌟 Highlights

- 🍔 **顶部 hamburger Settings** — 删 ⚙ 齿轮按钮,改用左侧 ☰ 三横线唤起 SettingsDrawer;Settings 不再是独立 tab
- 🎚️ **可调论文数量 3-30** — UI 双滑块,默认 5-10;与 budget/iter 并排
- 🎯 **LLM 检索模式严格 ≥ 8 分** — 真实有效文献门槛,iter 不够自动放宽到 ≥ 7,**绝不 mock fallback**;Local 模式允许 mock
- 📄 **Search 概要卡 + Report 居中** — Search tab 不再渲染完整报告,显示标题+Top 5+跳报告按钮;Report tab 内容居中显示
- 🪟 **修复 D3 图谱 hover 颤动 bug** — 主 D3 effect 移除 `hovered` deps,改用 hoveredRef,鼠标滑动节点位置稳定
- 🌐 **完整 i18n 覆盖** — ~180 key 中英双语:TopNav/Search/Report/Graph/History/Settings/Auth/CommandPalette/PipelineProgress 全部走 useT()

### 📦 Changes

**Frontend**
- `TopNav.tsx`: 删齿轮+加☰+删settings tab
- `QueryInput.tsx`: paperMin/Max 双滑块
- `GraphPage.tsx`: 删§4前缀+hoveredRef jitter fix
- `SearchSummary.tsx`: 新建 Search 概要卡
- `ReportView.tsx`: 内容居中+跳回Search按钮
- `SettingsDrawer.tsx`: 删 "midnight 主题天然是夜间模式" 文案
- `i18n/index.ts`: 全面化 (305→483 LOC,~180 key)
- 清理 3 个死文件: `frontend/src/hooks/useSearch.ts` (32KB) + `useLocalStorage.ts` (3.7KB) + `paperFilters.ts` (550B)

**Backend**
- `models.py`: SearchRequest 加 paperMin/Max;make_initial_state 加 score_threshold/score_relaxed
- `search.py`: SSE + POST 端点透传 paperMin/Max
- `ranker_agent.py`: LLM strict ≥ score_threshold 筛选 + thinking log
- `query_refiner.py`: 触发放宽 8.0→7.0 + score_relaxed 标记

### ✅ Verification

- `npx tsc --noEmit`: 0 errors
- `npm run build`: 619 modules, 2.31s, index 101.01 kB (gzip 28.70 kB)
- `python -c "from backend.agents.search_agent import search_node"`: OK
- `make_initial_state(runtime_mode='llm')` 返回 `score_threshold=8.0`

### 📚 Docs

- README.md / ROADMAP.md / BACKLOG.md / ChangelogModal / VERSION / package.json 全部同步到 R10.5.59 / v1.0.6

---

## R10.5.55 — 2026-06-21

**i18n 中英文切换 + D3 图谱独立 tab + SettingsDrawer + Auth 严格化**

- i18n 中英字典 + TopNav 中/EN 切换按钮
- D3 图谱完整复刻旧 GraphPanel 18 项特性 (filter / 2-hop / 全屏 / drag-to-fix / 富 tooltip / 社区颜色 / 双击打开) 作为独立 Graph tab
- SettingsView → SettingsDrawer (左侧滑出);删 isDark 独立暗黑模式
- runtimeMode 改名 `mock/real` → `local/llm`;LLM 检索模式不允许 mock fallback
- AuthDialog 拆 register/login 双 tab + 8 类错误信息 + `/auth/revoke` 自助轮换 + `/auth/logout`
- 7 agent 加 _step() thinking log + SSE 流式 emit + PipelineProgress 逐条 fade-in

## R10.5.54 — 2026-06-20

**Frontend complete rebuild — Editorial Desk Reference visual language**

- 新建 tokens.ts (OKLCH 主题) + useStore (单 store 取代 3 Contexts + 13 useState)
- TopNav / SearchWorkspace / QueryInput / PaperList / PipelineProgress / ReportView 12 组件
- 8 节点流水线 + 节点级 thinking log + build_graph 图谱演化 scrubber 合并到 PipelineProgress
- CockpitDashboard / CostDashboard / EvolutionSlider / PipelineStrip / HistoryPanel / SettingsPanel / ReportPanel / GraphPanel / QueryPanel 等 15 文件进入移除清单

## R10.5.53 — 2026-06-20

**4-tab routing + 图谱演化折叠**

- 4-tab routing (Search / Report / History / Settings)
- 删 R10.5.28 升级公告 banner
- 节点级思考日志 (query_decompose / query_refiner)