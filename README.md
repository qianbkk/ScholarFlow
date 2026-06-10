# ScholarFlow

> 面向研究生科研工作流的自主多 Agent 学术情报系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.1-blue.svg)](VERSION)

ScholarFlow 让用户输入一个复杂的学术研究问题，自动通过 **8 个串联的 LangGraph 节点**完成：查询理解与分解 → 多源并行检索 → 引文网络扩展 → 三维质检排序 → 自适应迭代优化 → 结构化综述报告 → 引文知识图谱 → 成本追踪汇报。

---

## 🎯 核心创新

| # | 创新 | 实现方式 |
|---|------|---------|
| 1 | **三维交叉质检** | 相关性 × 权威性 × 一致性 三维度独立评分加权 |
| 2 | **引文链自扩展** | 沿 top 引用论文的 references 自动扩展 1 跳 |
| 3 | **成本感知多模型路由** | 批量打分用轻量模型，复杂推理用旗舰模型 |
| 4 | **自适应查询迭代** | 质量不足时自动改写查询词再次搜索 |
| 5 | **D3.js 引文图谱** | 节点大小=log(引用数)，颜色=相关性，箭头=引用方向 |

---

## 🧱 技术栈

- **后端**: Python 3.11+ · LangGraph 0.2+ · FastAPI · httpx · Anthropic SDK · OpenAI SDK
- **前端**: React 18 · TypeScript · Vite · D3.js v7 · Tailwind CSS · marked
- **LLM**: MiniMax M3 (Anthropic 协议, 默认) · Kimi K2.6 (Anthropic 协议, 可换 K2.5 fast) · GLM-5.1 (主) / GLM-6 (fast) · Claude (官方) · DeepSeek (OpenAI 协议) · 内部 fallback (mock)
- **数据源**: Semantic Scholar Graph API · OpenAlex API

---

## 🚀 快速开始

### 0. 项目结构

```
ScholarFlow/
├── backend/         ← Python LangGraph + FastAPI
│   ├── agents/      ← 8 个 Agent 节点
│   ├── api/         ← SS + OpenAlex 客户端 (含 mock)
│   ├── workflow/    ← graph.py + router.py
│   ├── models/      ← Paper + SearchState
│   ├── utils/       ← llm_client + text_utils
│   ├── config.py
│   └── main.py      ← FastAPI 入口
├── frontend/        ← React 18 + TS + Vite + D3 + Tailwind
│   └── src/
│       ├── components/ ← CostDashboard / QueryPanel / ReportPanel / GraphPanel
│       ├── hooks/      ← useSearch
│       ├── services/   ← api
│       └── types/
├── test_run.py      ← 端到端冒烟测试
└── .env.example     ← 配置模板
```

### 1. 配置环境变量

```bash
cp .env.example .env
# 默认是 mock 模式，可立即跑通；有 API key 后改 .env
```

**两种运行模式**：

| 模式 | 设置 | 适用场景 |
|------|------|---------|
| **MOCK（默认）** | `LLM_MOCK=true` `API_MOCK=true` | 无网络 / 无 key / 演示 |
| **REAL** | `LLM_MOCK=false` `API_MOCK=false` + 填入有效 key | 实际运行 / 评测 |

MOCK 模式特点：
- LLM 调用走预置响应（query 分解、相关性评分、综述生成、查询改写）
- 学术 API 返回 57 篇真实存在的代表性论文（Transformer / BERT / GPT-3 / Llama 2 / GraphRAG 等, 50 SS + 8 OA 中 1 篇重复, deduplicate_papers 后剩 57）
- 流水线完整 8 节点全部跑通，输出可观察

### 2. 启动后端

```bash
# 启动 FastAPI（默认 8000 端口）
PYTHONIOENCODING=utf-8 uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 生产环境(可选):用 gunicorn 启动

```bash
# gunicorn 已在 backend/requirements.txt (生产 dep, 见 docs/DEPLOYMENT.md §1.2)
pip install -r backend/requirements.txt
gunicorn backend.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000 \
  --timeout 480
```

验证：
- 浏览器打开 `http://127.0.0.1:8000/api/v1/health` → `{"status":"ok",...}`
- `http://127.0.0.1:8000/docs` → Swagger API 文档
- `POST /api/v1/search` 提交 JSON: `{"query": "...", "max_iterations": 1, "budget": 0.5}`
- 浏览器打开 `http://127.0.0.1:5173/` 用 UI 体验 (推荐, 见下方 🛠 运维脚本)

### 3. 启动前端

```bash
cd frontend
npm install   # 已装好可跳过
npx vite --host 127.0.0.1 --port 5173
```

前端默认 `http://127.0.0.1:5173`，已配置 Vite 代理 `/api → 127.0.0.1:8000`。

> ⚠️ **Vite 代理仅开发环境有效**。生产部署需在前端服务器（nginx / caddy / cloudflare）显式反代 `/api` 到后端。示例 nginx 配置（与项目自带 `frontend/nginx.conf` 对齐，R10.5 修复 404 bug）：
>
> ```nginx
> location /api/ {
>     proxy_pass http://backend:8000;       # 末尾不要加 / — 斜杠会导致 /api/v1/* 404 (R10.5 复现)
>     #                                    # backend 是 docker-compose service 名; 单机部署改成 127.0.0.1:8000
>     proxy_set_header Host $host;
>     proxy_set_header X-Real-IP $remote_addr;
>     proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
>     proxy_set_header X-Forwarded-Proto $scheme;
>     proxy_read_timeout 600s;              # ≥ 后端 480s (R10.5 实测: 8 节点 + 双源 + 多次迭代)
>     proxy_buffering off;                  # SSE 必须
>     proxy_cache off;                      # SSE 必须
> }
> ```

### 4. 端到端冒烟测试

```bash
PYTHONIOENCODING=utf-8 python test_run.py
```

---

## 🏗️ 架构

### 流水线

```
START
  ↓
[① query_decompose]   Claude Sonnet 旗舰 → 4-5 个英文子查询
  ↓
[② search]            SS + OpenAlex 并行 → 原始论文
  ↓
[③ expand_citations]  Top5 高引论文的 references → 扩展池
  ↓
[④ rank]              LLM 相关性 + 规则权威性 + 一致性
  ↓
  ╔══════════ should_refine 决策 ══════════╗
  ║  iter >= max   → synthesize             ║
  ║  budget < $0.3 → synthesize             ║
  ║  papers < 5    → refine                 ║
  ║  avg_rel≥7 & n≥15 → synthesize          ║
  ║  否则          → refine                 ║
  ╚════════════════════════════════════════╝
  ↓
[⑤ query_refiner]     Claude Sonnet → 新查询词
  ↓ (迭代回 search)
[⑥ synthesize]        Claude Sonnet → Markdown 综述
  ↓
[⑦ build_graph]       纯计算 → D3 nodes/links
  ↓
[⑧ track_cost]        纯计算 → 成本报告
  ↓
END
```

### 前端三栏布局

```
┌────────────────── CostDashboard（顶部）──────────────────┐
│ Token / Cost / Papers / Status / Elapsed                │
├──────────────┬──────────────────┬───────────────────────┤
│  QueryPanel  │  ReportPanel     │  GraphPanel           │
│  左栏 25%    │  中栏 flex-1     │  右栏 30%             │
│  min 280px   │  (1440px 视口下  │  min 320px            │
│              │   约 45%)        │                       │
│  - 查询框    │  - Markdown 报告 │  - D3 力导向图 (4 边) │
│  - 参数      │  - marked+DOMPurify │ - 缩放/拖拽/平移    │
│  - 论文列表  │  - Copy/MD/BibTeX │  - 单击高亮/双击打开 │
│              │    /RIS 导出    │  - 右键取消固定       │
└──────────────┴──────────────────┴───────────────────────┘
```

> 列宽来源: `App.tsx` 父容器 `flex flex-col lg:flex-row`,各组件内部 className:
> - `QueryPanel`: `lg:w-1/4 lg:min-w-[280px]`
> - `ReportPanel`: `flex-1` (无固定宽度, 自动占满剩余)
> - `GraphPanel`: `lg:w-[30%] lg:min-w-[320px]`

---

## 📊 评测与质量保障

流水线在每轮迭代中执行以下质量检查：

- **数量检查** — 排序后论文数 ≥ 5 才进入综述
- **相关性检查** — Top 论文平均相关性 ≥ 7/10 才视为充分
- **预算检查** — 累计成本 < $0.3 才允许下一轮迭代
- **成本汇总** — 最后一节点统一汇总 tokens / USD / per-model 分摊

> **Mock 模式下的 F1**：因为内置数据集只有约 57 篇代表性论文（去重后），precision 受限（top-20 里会混入非期望论文）。这是 mock 数据池的固有限制，**真实 API 模式下会显著提升**。Recall 较高（≥0.85）说明流水线能正确识别并返回相关论文。

---

## 🐛 已知修复

| 组件 | 问题 | 修复 |
|------|------|------|
| `fastapi/routing.py` | FastAPI 0.115 内部 `APIRouter.__init__` 把 `on_startup/on_shutdown` 传给父类 `starlette.routing.Router`，但父类不接收 | 移除 super() 调用中的这两个参数 |
| `Paper(**d)` | 反序列化时临时 `references` 字段导致 `__init__` 抛异常 | 在 `Paper` 加 `references: list[str]` 字段 + `from_dict` 安全构造 |
| `_to_paper()` | 把 Paper 对象当 dict 用了 | 改用属性访问 `p.year` |
| `useSearch.ts` | 一开始写成 Python `try:` 语法 | 改回 TypeScript `try { }` |
| `GraphNode` | D3 simulation 需要 `x/y/fx/fy` 字段 | 扩展 `SimNode extends GraphNode` |
| 终端 GBK 编码 | `✅⚠️` emoji 打印异常 | 改用 `[OK]/[!]/[PASS]` 纯 ASCII |

---

> R10.5+ 的 P0-P3 审计修复 (白屏 / 重复 auth / 循环导入 / CVE 白名单 / DB init / user_id 一致 /
> fallback root cause / 4.0 分全一致 / 图谱交互 / vite 404 / scholarflow.bat 等) 详见
> [CHANGELOG.md §1.0.1](CHANGELOG.md#101---2026-06-10)

---


---

## 🔑 切换到多用户 + API Key 认证 (可选)

默认 `OPEN_MODE=true` 跳过认证（单用户开发用）。生产 / 多用户场景：

```bash
OPEN_MODE=false                    # 强制校验 X-API-Key
# 启动后: 浏览器打开 UI 首次访问会弹出注册/登录对话框
# 或手动:
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","display_name":"You"}'
# 拿到 api_key → 后续请求 header 'X-API-Key: sf_xxx' 携带
```

> R10.5 多用户 API key 走 SQLite (sha256 摘要, 不存明文)。详见 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。

---

## 🔐 切换到真实 LLM 模式

编辑 `.env`：

```bash
# 关闭 mock
LLM_MOCK=false
API_MOCK=false

# 选择 LLM provider（kimi / glm / minimax / anthropic / deepseek）
LLM_PROVIDER=kimi

# 填入对应 key（参考 .env.example）
KIMI_API_KEY=sk-...
```

然后重启后端即可。

---

## 📜 License

MIT — see [LICENSE](LICENSE).

当前版本: [VERSION](VERSION) ([CHANGELOG](CHANGELOG.md))

## 💬 Community & Discussion

ScholarFlow 还在积极迭代中，欢迎你参与！

- 📋 [GitHub Discussions](https://github.com/qianbkk/ScholarFlow/discussions) — 提问 / 想法 / 学术反馈
- 🐛 [Issue Tracker](https://github.com/qianbkk/ScholarFlow/issues) — Bug 报告
- 📖 [Q&A](https://github.com/qianbkk/ScholarFlow/discussions/categories/q-a) — 使用问题 / 安装问题

> R10+ 计划：把 Discussion categories 进一步细分（学术 / 工程 / 安全），目前先用 GitHub 内置 categories。

## 🛠 运维脚本 (Windows)

`scholarflow.bat` 是项目根目录的一键管理脚本（Windows，双击或在 cmd 调）：

| 选项 | 作用 |
|------|------|
| `1` | 启动 - 本地模式 (uvicorn + vite) |
| `2` | 启动 - Docker 模式 (docker-compose) |
| `3` | 停止 |
| `4` | 重启 |
| `5` | 查看状态 (PID + 端口 + curl 健康检查) |
| `6` | 查看日志 (后30行 / 实时 tail) |
| `7` | 安装依赖 (Python / Node / Docker 镜像) |
| `8` | 清理缓存 (backend/.cache + logs + frontend/dist) |
| `9` | 浏览器打开 (前端 + API 文档) |
| `0` | 退出 |

PID 文件在 `.run/`,日志在 `logs/`,都已加入 `.gitignore`。

## 🔒 Security & Privacy

- 报告漏洞请走 **[SECURITY.md](SECURITY.md)**（非公开渠道，48h 内响应）
- 容器默认非 root 运行 (UID 1000)，根 fs read-only，详见 [`Dockerfile.backend`](Dockerfile.backend) + [`docker-compose.yml`](docker-compose.yml)
- 输入 sanitize 阻断 CJK 注入 / jailbreak / DAN / developer mode，详见 `backend/api/utils/`
- API key 仅存 `.env`（不进 git），生产推荐 K8s Secret / Docker `-e`

## 📚 文档

- [CONTRIBUTING.md](CONTRIBUTING.md) — 如何贡献
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — 行为准则
- [SECURITY.md](SECURITY.md) — 安全策略（含漏洞报告流程）
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — 生产部署 (systemd / Docker Compose / K8s)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构 / ADR / SearchState 字段表
- [docs/HANDOFF.md](docs/HANDOFF.md) — AI 接手清单 + P0-P3 待办
- [docs/FUTURE_TASKS.md](docs/FUTURE_TASKS.md) — 推迟项列表
- [.editorconfig](.editorconfig) / [.gitattributes](.gitattributes) — 代码风格 / 行尾
