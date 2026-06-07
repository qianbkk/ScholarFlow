# ScholarFlow

> 面向研究生科研工作流的自主多 Agent 学术情报系统

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
- **LLM**: Kimi K2.5 (Anthropic 协议, 可换 K2.6) · GLM-4.6 · MiniMax-M3 · Claude (官方) · DeepSeek (OpenAI 协议)
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
- 学术 API 返回 ~58 篇真实存在的代表性论文（Transformer / BERT / GPT-3 / Llama 2 / GraphRAG 等）
- 流水线完整 8 节点全部跑通，输出可观察

### 2. 启动后端

```bash
# 启动 FastAPI（默认 8000 端口）
PYTHONIOENCODING=utf-8 uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 生产环境(可选):用 gunicorn 启动

```bash
pip install gunicorn
gunicorn backend.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000 \
  --timeout 240
```

验证：
- 浏览器打开 `http://127.0.0.1:8000/health` → `{"status":"ok",...}`
- `http://127.0.0.1:8000/docs` → Swagger API 文档
- `POST /search` 提交 JSON: `{"query": "...", "max_iterations": 1, "budget": 0.5}`

### 3. 启动前端

```bash
cd frontend
npm install   # 已装好可跳过
npx vite --host 127.0.0.1 --port 5173
```

前端默认 `http://127.0.0.1:5173`，已配置 Vite 代理 `/api → 127.0.0.1:8000`。

> ⚠️ **Vite 代理仅开发环境有效**。生产部署需在前端服务器（nginx / caddy / cloudflare）显式反代 `/api` 到后端。示例 nginx 配置：
>
> ```nginx
> location /api/ {
>     proxy_pass http://127.0.0.1:8000/;   # 注意末尾斜杠：剥掉 /api 前缀
>     proxy_set_header Host $host;
>     proxy_set_header X-Real-IP $remote_addr;
>     proxy_read_timeout 300s;              # 大于后端 240s 超时 (8 节点 LLM + 双源检索最多需 180s+)
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
[⑤ refine]            Claude Sonnet → 新查询词
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
│  左栏 25%    │  中栏 45%        │  右栏 30%             │
│  - 查询框    │  - Markdown 报告 │  - D3 力导向图        │
│  - 参数      │  - marked 渲染   │  - 节点悬浮摘要       │
│  - 论文列表  │                  │  - 拖拽 + 点击跳转     │
└──────────────┴──────────────────┴───────────────────────┘
```

---

## 📊 评测与质量保障

流水线在每轮迭代中执行以下质量检查：

- **数量检查** — 排序后论文数 ≥ 5 才进入综述
- **相关性检查** — Top 论文平均相关性 ≥ 7/10 才视为充分
- **预算检查** — 累计成本 < $0.3 才允许下一轮迭代
- **成本汇总** — 最后一节点统一汇总 tokens / USD / per-model 分摊

> **Mock 模式下的 F1**：因为内置数据集只有约 58 篇代表性论文，precision 受限（top-20 里会混入非期望论文）。这是 mock 数据池的固有限制，**真实 API 模式下会显著提升**。Recall 较高（≥0.85）说明流水线能正确识别并返回相关论文。

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

## 🛡️ Round 5 优化 (2026-06-07)

历经 5 轮密集审计+优化,本轮聚焦 **生产化硬化**:

| 类别 | 项 | 描述 |
|------|---|------|
| **M-1** | `SearchResponse.is_degraded_response` 顶层信号 | 任一 paper fallback → 整篇响应标记为 degraded,前端 banner 闭环 |
| **M-2** | `load_dotenv(override=True)` → `False` | 修复 K8s/Docker secret 部署时静默被 .env 覆盖 |
| **M-3** | HTTP 7 个安全头 + `TrustedHostMiddleware` | X-Frame-Options / HSTS / CSP / X-Content-Type-Options 等 |
| **M-4** | `model_usage` 字段白名单 | 去除 cost + provider 内部名泄露 (如 `MiniMax-M3 (fallback to mock)`) |
| **S-1** | LLM token 浪费 3 处 | synthesis 25→15 papers, abstract 400→200 字符, decompose max_tokens 800→500 |
| **S-2** | CJK prompt 注入 denylist | 中文/日文/韩文"忽略指令"关键词 |
| **S-3** | Pydantic 422 不回显 input | 防日志注入 + 隐私 |
| **S-4** | `/search/cancel` 限流 + 校验 | 10/minute + request_id 长度/charset |
| **S-5** | 前端真调 `/search/cancel` | reset 不只关 EventSource,让后端停 in-flight pipeline |
| **M-5** | useSearch setInterval 4Hz → 1Hz | 减少 75% setState 次数 (800 re-render → 200) |
| **S-8** | D3 alphaDecay 调优 | 加快收敛 1 倍, 拖拽停止更平滑 |
| **SIMPLIFY** | 抽 `_build_search_response` helper | 消除 /search + /search/stream ~30 行重复 |
| **SIMPLIFY** | 删 `usingFallback` 死状态 | 前端 0 处读的 state + 4 处 set |
| **TEST** | 7 个新测试 | 覆盖 M-1/M-3/M-4/S-3/S-4 |
| **DEFER** | 9 项入 `docs/FUTURE_TASKS.md` | Dockerfile / 多 worker / K8s / 日志结构化 / etc. |

**总 commit 数**: 第 5 轮 **15 个 commit**(含 docs 追加),累计 5 轮共 **~60+ commits**。

详见 `docs/FUTURE_TASKS.md` 了解推迟项。

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

## 📚 文档

- [CONTRIBUTING.md](CONTRIBUTING.md) — 如何贡献
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — 行为准则
- [SECURITY.md](SECURITY.md) — 安全策略
- [docs/FUTURE_TASKS.md](docs/FUTURE_TASKS.md) — 推迟项列表
- [.editorconfig](.editorconfig) / [.gitattributes](.gitattributes) — 代码风格 / 行尾
