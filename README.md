# ScholarFlow

> **多 Agent 学术文献综述工具** · 提问 → 8 节点 LangGraph 流水线 → 带引用的 Markdown 报告 + D3 引文图谱 + 完整 thinking 日志。
>
> **当前版本**: R10.5.59 (frontend/backend 迭代改进) · build on `R10.5.54 frontend rebuild` + `R10.5.55 i18n + auth + graph` + `R10.5.59 paper_count + LLM strict ≥ 8`

Ask a research question in Chinese or English. A real LangGraph pipeline lights up — decompose → search (Semantic Scholar / OpenAlex / arXiv / Crossref / PubMed) → expand citations → 3D rank → refine → synthesize → build graph → track cost. The output is a Markdown report with numbered citations, a D3 force-directed citation graph, real-time thinking logs, and BibTeX / RIS export.

---

## ✨ Highlights

- **完整 8 节点 LangGraph 流水线** — 每个节点 emit `_step()` thinking 日志,SSE 流式推到前端 `PipelineProgress`,逐条 fade-in 展示思考过程
- **LLM 检索模式 strict ≥ 8 分** — 真实有效文献门槛,iter 不够自动放宽到 ≥ 7,**绝不 mock fallback**;本地模式允许 mock (离线演示)
- **可调论文数量 3-30** — UI 双滑块,默认 5-10
- **D3 完整图谱独立 tab** — filter bar (year + author) / 2-hop 高亮 / 8 色社区 / 4 类边 + marker / drag-to-fix / 全屏 / f 适配 / 富 tooltip
- **完整 i18n** — TopNav / Search / Report / Graph / History / Settings / Auth / CommandPalette / PipelineProgress 全部中英双语切换 (`中 ⇄ EN` 按钮)
- **左侧 Settings drawer** — ☰ 三横线按钮唤起;主题色/runtime mode/API key/键盘/关于 6 分组
- **认证系统** — Register / Login 双 tab + 5 类错误区分 + `/auth/revoke` 自助轮换 key + `/auth/logout` 真正登出
- **Search 概要 + Report 居中** — Search tab 不再渲染完整报告,显示标题+Top 5+跳报告按钮;Report tab 居中(maxWidth 720)

## 🏗 架构 (3 层)

```
┌──────────────────────────────────────────────────────────────┐
│ Frontend (React 18 + TS strict + Vite)                       │
│   • 14 组件 + 单 useStore (useSyncExternalStore)             │
│   • 4 tab: 查询 / 报告 / 图谱 / 历史                        │
│   • SettingsDrawer (左侧) + CommandPalette (Cmd+K)           │
│   • SSE 客户端 + 节点 thinking log fade-in 动画              │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Backend (FastAPI + LangGraph)                                │
│   • 8-node pipeline (backend/agents/*.py)                    │
│   • SearchRequest {paper_min/paper_max} + runtime_mode       │
│   • /search (POST) + /search/stream (SSE) + /auth/{*}        │
│   • auth + budget guard + cost tracker + cache               │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Data sources (5 academic APIs)                               │
│   Semantic Scholar · OpenAlex · arXiv · Crossref · PubMed    │
│   (mock fallback 仅 'local' runtime mode)                    │
└──────────────────────────────────────────────────────────────┘
```

## 🚀 Quick start

### 后端 (:8000)

```bash
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

跨平台启动器:
```bash
python scripts/scholarflow.py start    # 一键启动 / 停止 / 看日志
python scripts/scholarflow.py --help   # 所有子命令
```

### 前端 (:5173)

```bash
cd frontend
npm install
npm run dev
# → http://127.0.0.1:5173/
```

### 环境变量

```bash
cp .env.example .env
# 必须: OPEN_MODE=true (无需注册即可用)
# 或: 设 LLM_API_KEY (kimi / glm / minimax / anthropic)
```

## 🎯 8 节点流水线

| # | 节点 | 作用 |
|---|---|---|
| 0 | `query_decompose` | 拆 3-5 个子查询 |
| 1 | `search` | 5 源并行检索 (LLM 模式去掉 mock fallback) |
| 2 | `expand_citations` | 向后 + 向前引文扩展 |
| 3 | `rank` | 三维评分 (relevance/authority/consistency);**LLM 模式 strict ≥ 8** |
| 4 | `refine` | 不足时放宽到 ≥ 7 + 生成补充 sub_queries |
| 5 | `synthesize` | LLM 综述生成 + 引文校验 |
| 6 | `build_graph` | 构建 D3 引文图谱 (4 类边) |
| 7 | `track_cost` | 成本 / tokens / elapsed 汇总 |

## ⌨️ 快捷键

| Key | Action |
|---|---|
| `⌘ K` / `Ctrl K` | 打开命令面板 |
| `⌘ ↵` / `Ctrl ↵` | 提交查询 |
| `Esc` | 关闭弹窗 / 清选中 / 退出图谱全屏 |
| `f` (在 Graph) | 适配视图 (fit-to-view) |
| `Shift+F` (在 Graph) | 全屏图谱 |
| `?` | 显示快捷键 |

## 📦 导出

- `.bib` (BibTeX, 导入 Zotero / Mendeley)
- `.ris` (RIS, 导入 EndNote)
- `.md` (原始 Markdown 报告)

## 🗂 项目结构

```
Atest/
├── backend/
│   ├── agents/             # 8 节点 + _schemas / _state_utils / _step_helper
│   ├── api/routes/         # search / auth / admin / health
│   ├── auth/               # PBKDF2 + SQLite WAL
│   ├── models/             # Pydantic SearchRequest / SearchState TypedDict
│   ├── utils/              # budget / cache / runtime_mode / sanitize / observability
│   ├── workflow/           # LangGraph graph + router
│   └── main.py             # FastAPI app + lifespan
├── frontend/
│   ├── src/
│   │   ├── components/     # 14 组件 (TopNav / SearchWorkspace / ReportView / GraphPage / HistoryView / SettingsDrawer / AuthDialog / CommandPalette / ChangelogModal / CompareDrawer / PipelineProgress / QueryInput / PaperList / SearchSummary)
│   │   ├── i18n/           # 中英字典 + useT hook
│   │   ├── store/          # useStore (单 store + useSyncExternalStore)
│   │   ├── lib/            # tokens (OKLCH) + storageKeys
│   │   ├── services/       # api.ts (register / login / revokeKey / logout / SSE)
│   │   ├── types/          # 共享类型
│   │   ├── App.tsx / commands.ts / main.tsx / index.css
│   └── vite.config.ts + tailwind.config.js
├── docs/
│   ├── ARCHITECTURE.md     # 后端架构详述
│   ├── DEPLOYMENT.md       # systemd + Docker + K8s
│   └── ADR/                # 0001 HTTP-only session / 0002 dual-version / 0003 mock pipeline
├── tests/                  # pytest unit + e2e
├── scripts/scholarflow.py  # 跨平台启动器
├── BACKLOG.md              # 唯一跟踪文件 (清理/重构/漂移/P0/P1)
├── ROADMAP.md              # R11+ 战略方向 + 历史记录
├── VERSION                 # 当前版本
└── README.md (本文件)
```

## 📚 文档

- [`BACKLOG.md`](BACKLOG.md) — 唯一跟踪文件:C/D/E/F/G 5 类清理/重构/漂移/跳过 P0/P1/中优先级/低优先级/不做
- [`ROADMAP.md`](ROADMAP.md) — R11+ 战略方向 (LangGraph 1.0 / Memory Layer / Multi-Agent Runtime / Sandbox / K8s / i18n) + 历史发布记录
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 后端架构 (8 节点 / 状态机 / 数据流)
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — 部署 (systemd / Docker Compose / K8s)
- [`docs/ADR/`](docs/ADR/) — 架构决策记录 (HTTP-only session / dual-version / mock pipeline)
- [`RELEASES.md`](RELEASES.md) — GitHub Releases 草稿区 (每版本一段可直接 copy-paste)
- `.claude/skills/impeccable/` — 本地安装的 [pbakaus/impeccable](https://github.com/pbakaus/impeccable) 设计技能,可用 `/impeccable craft / shape / critique / audit / polish`

## 📝 Release notes

最新 5 个版本 (详细见 ChangelogModal 在 App 内):

- **R10.5.59** (2026-06-21) — hamburger Settings / paper_count 滑块 / LLM strict ≥ 8→7 / 搜索概要+报告居中 / 图谱 jitter 修复 / 完整 i18n 覆盖
- **R10.5.55** (2026-06-21) — i18n 中英文切换 / D3 图谱独立 tab 完整复刻 / SettingsDrawer 替换 Settings tab / runtimeMode 改名 + 拒降级 / Auth 严格化 (Register/Login/revoke)
- **R10.5.54** (2026-06-20) — frontend 完全重构: Editorial Desk Reference 视觉 / 14 组件 + 单 store
- **R10.5.53** (2026-06-20) — 节点级 thinking log / 图谱演化折叠
- **R10.5.51** (2026-06-19) — `/simplify` 8 项清理 + STORAGE_KEYS 中央化 + BACKLOG.md 统一跟踪

## 📄 License

MIT. See [`LICENSE`](LICENSE).

## ✍️ Author

[qianbkk](https://github.com/qianbkk) — [github.com/qianbkk/ScholarFlow](https://github.com/qianbkk/ScholarFlow)