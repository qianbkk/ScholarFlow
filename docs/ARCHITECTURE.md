# ScholarFlow 架构文档

> **项目**: ScholarFlow — 8 节点多 Agent 学术文献搜索系统
> **版本**: v1.0.0 (R10 — 语义缓存 + 架构文档落地)
> **最后更新**: 2026-06-08
> **受众**: 新加入项目的工程师 / 代码审计员 / R11+ 维护者

---

## 1. 系统总览

ScholarFlow 是一个 **多 Agent 学术文献搜索 + 综合报告生成** 系统。前端输入研究问题,后端跑 8 节点 LangGraph 流水线,最终返回论文列表 + 引文图谱 + 合成报告 + 成本统计。

```
┌────────────────────────────────────────────────────────────────────┐
│                       ScholarFlow System                           │
│                                                                    │
│  ┌──────────┐    ┌────────────────────────────────────┐           │
│  │ Frontend │───▶│ FastAPI  (backend/main.py)         │           │
│  │ React TS │    │  • /search   (POST, 240s timeout)  │           │
│  └──────────┘    │  • /search/stream (SSE)            │           │
│                  │  • /health, /providers             │           │
│                  │  • /search/cancel                  │           │
│                  └──────┬─────────────────────────────┘           │
│                         │                                          │
│                         ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ 8-Node LangGraph Pipeline (backend/workflow/graph.py)        │  │
│  │                                                              │  │
│  │  START                                                       │  │
│  │    │                                                         │  │
│  │    ▼                                                         │  │
│  │  [0] query_decompose  → 拆 3-5 个子查询                     │  │
│  │    │                                                         │  │
│  │    ▼                                                         │  │
│  │  [1] search           → Semantic Scholar + OpenAlex 双源    │  │
│  │    │                       并发检索 (250 papers, 125/源)     │  │
│  │    ▼                                                         │  │
│  │  [2] expand_citations → 引文图扩展 (semaphore 限并发 5)     │  │
│  │    │                                                         │  │
│  │    ▼                                                         │  │
│  │  [3] rank             → 三维打分 (relevance/consistency/     │  │
│  │    │                       authority)                         │  │
│  │    ▼                                                         │  │
│  │  [4] refine? (条件)  ─┐                                      │  │
│  │    │  yes            │ no                                   │  │
│  │    ▼                 │                                      │  │
│  │  [4a] refine         │                                      │  │
│  │    │  (回 [1] search) │                                      │  │
│  │    │                 ▼                                      │  │
│  │  [5] synthesize      → 15 篇论文综合, grounding 验证        │  │
│  │    │                                                         │  │
│  │    ▼                                                         │  │
│  │  [6] build_graph     → 引文网络 (nodes + links JSON)         │  │
│  │    │                                                         │  │
│  │    ▼                                                         │  │
│  │  [7] track_cost      → USD/tokens 累加 + model_usage 白名单  │  │
│  │    │                                                         │  │
│  │    ▼                                                         │  │
│  │  END                                                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                         │                                          │
│                         ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Persistent Storage                                           │  │
│  │  • SQLite WAL cache: backend/.cache/search_cache.sqlite      │  │
│  │  • SQLite budget ledger: backend/.cache/budget_state.json    │  │
│  │    (mirror: backend/api/services/budget.py)                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 1.1 关键设计原则

- **节点顺序 + 条件分支**: 8 个节点中 7 个是线性边,只有 `rank → {refine, synthesize}` 是 `should_refine` 条件路由
- **预算硬停止**: R5 起每个节点出口调用 `check_budget(actual_cost, budget_limit)`,超出则 SSE `budget_exceeded` 事件 + 立即 `return`
- **跨迭代去重**: `expanded_paper_ids` 字段防止同一 paper 在 refine → search 回路里被 `get_references` 重复调
- **provider 隔离**: cache_key / model_usage / budget 都按 provider 维度分桶,kimi/glm/anthropic/deepseek/minimax 不串

---

## 2. State 字段表 (SearchState TypedDict)

> **位置**: `backend/models/state.py` — 单一来源,所有节点读写都按这张表
> **约束**: 节点写新字段时**必须**先在此处显式声明,否则静态测试 + 节点契约漂移

| 字段 | 类型 | 写者节点 | 读者节点 | 用途 |
|------|------|---------|---------|------|
| `original_query` | `str` | (入口) `main.py` | `query_decompose` | 原始用户查询(sanitize 后) |
| `sub_queries` | `list[str]` | `query_decompose` | `search` | 3-5 个拆分子查询 |
| `raw_papers` | `list[dict]` | `search` | `expand_citations` | 原始检索结果 ~250 篇 |
| `expanded_papers` | `list[dict]` | `expand_citations` | `rank` | 引文扩展后 ~300-500 篇 |
| `ranked_papers` | `list[dict]` | `rank` | `refine` / `synthesize` | 打分排序后 Top N |
| `report` | `str` | `synthesize` | (输出) | 综合报告 markdown |
| `citation_graph` | `dict` | `build_graph` | (输出) | `{nodes: [...], links: [...]}` |
| `iteration` | `int` | `query_refine` | `query_decompose`, `should_refine` | 当前迭代轮数 (0/1/2) |
| `max_iterations` | `int` | (入口) `main.py` | `should_refine` | 最多迭代轮数 (1-5) |
| `expanded_paper_ids` | `list[str]` | `expand_citations` | `expand_citations` | 已扩展去重,防重复调 API |
| `total_tokens_used` | `int` | `track_cost` | (输出) | LLM token 累计 |
| `total_cost_usd` | `float` | `track_cost` | `check_budget` | USD 累计,R5 起每节点查 |
| `budget_limit_usd` | `float` | (入口) `main.py` | `check_budget`, `track_cost` | 入口预算 |
| `model_usage` | `dict` | `track_cost` | (输出) | `{model: {tokens, cost}}` 白名单 |
| `status` | `PipelineStatus` | 多个 | SSE 事件, 日志 | 状态机推进(decomposing → done) |
| `error` | `Optional[str]` | (异常路径) | 日志, 错误响应 | 错误信息 |
| `provider` | `Optional[str]` | (入口) `main.py` | 所有调用 LLM 的节点 | 透传到 `call_llm` |
| `request_id` | `Optional[str]` | (入口) `main.py` | 所有节点, 日志 | 全链路追踪 ID (X-Request-ID) |
| `top5_summary_cache` | `Optional[str]` | `query_refine` | `query_refine` | 跨 retry 复用, 避免 LLM 重复摘要 |

### 2.1 状态机 (`PipelineStatus`)

```
decomposing → searching → expanding → ranking →
  checking_refine → (refining ↺) → synthesizing →
    building_graph → done
                  ↘ error (任何节点异常)
```

---

## 3. 缓存层

### 3.1 精确匹配缓存 (`backend/utils/cache.py`)

- **存储**: `backend/.cache/search_cache.sqlite` (WAL 模式)
- **键**: `sha256(query|iter|budget|provider)[:32]` — 跨 provider 隔离 (R4 P1)
- **值**: `response_json + cost_usd + tokens + created_at`
- **TTL**: `CACHE_TTL_SECONDS` (默认 86400s = 24h)
- **开关**: `ENABLE_SEARCH_CACHE=false` 全局关
- **并发**: `busy_timeout=5s` + 指数退避重试 (Gunicorn 多 worker 不会 500)
- **隐私**: H8 起只存 `query_hash`,**不存 query 文本** — 旧表迁移时 VACUUM 擦除

### 3.2 语义缓存 (`backend/utils/semantic_cache.py`) — R10 新增

- **存储**: 同一 `search_cache.sqlite`,新增 `query_embedding BLOB` 列 (float32 × 384 dim)
- **键**: numpy 384 维 L2-normalized 向量 (FNV-1a hash trick + 词袋 + L2 norm)
- **检索**: 拉最近 200 条 embedding → numpy 余弦相似度 top-1 → 阈值 0.92 视为命中
- **轻量 embedding**: 无外部依赖 (生产版可换 `sentence-transformers`)
- **退化兼容**: BLOB 列未写入或缺失时 `get_semantic_cached` 返回 None,自动 fallback 到精确匹配
- **不依赖**: 不联网,不调 LLM,纯 numpy 计算 <1ms/query

### 3.3 缓存调用位置

```
/search (POST) 入口
  └─ 1. get_semantic_cached (numpy cos-sim, 阈值 0.92) ← R10 新增
  └─ 2. get_cached_async (精确 hash 匹配)              ← 已有
  └─ 3. 跑 8 节点 pipeline (cache miss 时)
  └─ 4. set_cached_async (写精确缓存)
  └─ 5. set_semantic_cached (写 BLOB embedding)         ← R10 新增

/search/stream (SSE) 入口 — 同上
```

---

## 4. 安全边界 (Security Perimeter)

### 4.1 输入净化 (`backend/utils/sanitize.py`)

| 层级 | 措施 | 文件位置 |
|------|------|---------|
| Layer 0 | NFKC 规范化 + 数学字母归一化 + 同形字映射 | `sanitize.py:_normalize_math_chars` |
| Layer 0 | 注入特征词 denylist (英文 + CJK + jailbreak) | `sanitize.py:_INJECTION_PATTERNS` |
| Layer 0 | 控制字符剥除 + 长度截断 (max 2000) | `sanitize.py:sanitize_query` |
| Layer 1 | XML 标签隔离 (`<user_query>`) | `sanitize.py:wrap_user_input` |
| Layer 2 | LLM 输出端 denylist | `synthesis_agent.py` |

### 4.2 HTTP 安全 (`backend/middleware.py` + `main.py`)

| 措施 | 头/位置 | 用途 |
|------|---------|------|
| CORS 白名单 | `ALLOWED_ORIGINS` env | 禁止 `*` 通配符 (R5 修复) |
| 7 个安全头 | `SecurityHeadersMiddleware` | CSP / HSTS / X-Frame-Options / X-CTO / Referrer-Policy / Permissions-Policy / X-XSS-Protection |
| TrustedHost | `TrustedHostMiddleware` | 防止 Host header 注入 |
| /docs 门控 | `EXPOSE_DOCS=false` | 生产环境隐藏 OpenAPI 文档 |
| 422 不回显 input | `validation_exception_handler` | 防日志注入 + 隐私泄露 |
| X-Request-ID DoS 防护 | 长度 ≤ 128 + charset `[A-Za-z0-9_-]` | 防止 10MB header 撑爆日志 |

### 4.3 速率限制 (`slowapi`)

- `/search`: **5/minute;20/hour** (按 IP)
- `/search/stream`: **5/minute;20/hour**
- `/search/cancel`: **10/minute**
- 超出 → 429 (限流异常处理器)

### 4.4 预算闸门 (`backend/api/services/budget.py`)

- 全局 USD/hour 预算 (`BUDGET_LIMIT_USD` env, 默认)
- 入口 reserve → pipeline 跑 → 出口 return (try/finally 兜底)
- 节点级硬停止: R5 起每节点出口 `check_budget(actual_cost, limit)`,超则 SSE 中断

### 4.5 Provider 隔离 (R8)

- `_resolve_provider` 未知 provider **直接 raise**,不再静默回退
- `has_key=False` provider **从候选剔除**
- `_PROVIDER_HEALTH_CACHE` 5 分钟 TTL,定时后台刷新

---

## 5. ADR 列表 (Architecture Decision Records)

> 关键决策按 R1-R10 时序排列。每条 ADR 包含:**决策 / 替代方案 / 取舍 / 影响**。

### R1 — 多 provider 路由 + 模型选择器

- **决策**: 抽象 `LLMProvider` 接口,支持 kimi/glm/anthropic/deepseek/minimax
- **替代**: 硬编码单一 provider
- **取舍**: 多一层抽象,新 provider 加 ~50 行 boilerplate
- **影响**: cache_key 加 `provider` 维度 (R4 闭环)

### R2 — 跨 worker 预算 `BEGIN IMMEDIATE` + 归还

- **决策**: 用 SQLite `BEGIN IMMEDIATE` 拿排他锁 + reservation ledger
- **替代**: Gunicorn 内存 dict (多 worker 不共享)
- **取舍**: SQLite 单点写锁,高并发排队
- **影响**: 节点级硬停止 (R5) 同一机制

### R3 — SSE 推送节点进度 + 真 cancel 按钮

- **决策**: `astream(stream_mode="updates")` 每节点推 `node_complete` 事件
- **替代**: 客户端轮询 `/search/status?request_id=...`
- **取舍**: SSE 长连接占 server 资源,但用户体验流畅
- **影响**: cancel 端点需要 in-flight task table (R6 闭环)

### R4 — cache_key 跨 provider 隔离

- **决策**: hash 拼入 `provider or 'default'` 段
- **替代**: 维持旧 key (跨 provider 共享)
- **取舍**: 接受一次 cache 失效 (旧 key 视为新 key 失效)
- **影响**: 杜绝 kimi 缓存命中 glm provider 的污染

### R5 — 节点级预算硬停止 + 7 个 HTTP 安全头 + 6 维 sanitize

- **决策**:
  - 每个节点出口 `check_budget` → 超则 SSE `budget_exceeded` + `return`
  - 7 个 HTTP 安全响应头 (CSP/HSTS/X-Frame-Options/X-CTO/Referrer-Policy/Permissions-Policy/X-XSS-Protection)
  - NFKC + 同形字 + 0-width + CJK denylist + XML 标签 + max_length=2000
- **替代**: 仅在响应完成时检查 (用户感知的延迟)
- **取舍**: 多一次 cost check (毫秒级)
- **影响**: 422 不回显 input, X-Request-ID DoS 校验 (同 R5 闭环)

### R6 — In-flight task table + 日志 throttle + TypedDict 显式声明

- **决策**:
  - `_in_flight_searches[request_id] = asyncio.Task` 真取消
  - `log_throttle` 抽 utils,5 分钟去重
  - `SearchState` 显式声明 `top5_summary_cache` (消除"约定俗成"漂移)
- **替代**: cancel 端点返 `cancelled=True` 谎报 (R6 修复)
- **影响**: model_usage_summary 字段白名单 (避免 provider 内部名泄露)

### R7 — sanitize denylist 学术词误杀修正

- **决策**:
  - 移除独立 `\bdan\b` (DAN = Deep Adaptive Network, 大量 CS 论文标题)
  - `(developer|dev|admin|root) mode` 加 `enable/activate/unlock` 上下文才 ban
  - 保留 `\bjailbreak\b` (单字攻击向量, FP 风险低)
- **替代**: 维持严格 denylist (大量 FP)
- **影响**: 学术检索召回率提升, 攻击召回率几乎不变

### R8 — provider 严格语义 + aiosqlite 文档化

- **决策**:
  - `_resolve_provider` 未知 provider raise
  - `ProviderInfo.verified` + `model_usage_summary` 必填 + `model_usage` 可选
  - 同步 SQLite 包装文档化 (aiosqlite 重构留 R8+ 后续)
- **影响**: `_PROVIDER_HEALTH_CACHE` 跨文件污染 (R8.3 修) + conftest `autouse _reset_global_state` (R8.2)

### R8.2/R8.3 — 测试隔离强化

- **决策**:
  - R8.2: `_reset_global_state` autouse fixture 重置 limiter + in-flight table
  - R8.3: `test_cors_hardening` 改 subprocess reload 隔离 (跨文件模块级状态污染)
- **影响**: 27+ 测试稳定, 9 个 flaky 测试归零 (R6 起累计)

### R9 — 死代码清理 (同步版 cache API)

- **决策**: 删 `get_cached` / `set_cached` / `_retry_sqlite_op` (生产从未调用)
- **替代**: 维持双 API (调用方按需选)
- **影响**: 减少 ~80 行, 公共 API 收敛到 `get_cached_async` / `set_cached_async`

### R10 — 语义缓存 + 架构文档 (M-D 当前)

- **决策**:
  - `search_cache` 表加 `query_embedding BLOB` 列 (idempotent ALTER)
  - `backend/utils/semantic_cache.py` numpy 384 维余弦相似度 top-1, 阈值 0.92
  - `docs/ARCHITECTURE.md` 单一来源
  - `requirements.lock` 锁版本 (手写,非 pip-compile)
- **替代**: 接 sentence-transformers (重 ~400MB,首次冷启动慢)
- **取舍**: numpy 近似 embedding 召回率不如真 transformer,但零依赖 + <1ms
- **影响**: 语义相似查询可命中, P99 LLM 调用次数 ↓ (待 R11 实测)

---

## 6. 部署架构

```
┌─────────────────────────────────────────────────────┐
│  Production (Gunicorn + Uvicorn workers)           │
│                                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │Worker 1 │  │Worker 2 │  │Worker N │  (N=4-8)   │
│  │FastAPI  │  │FastAPI  │  │FastAPI  │            │
│  │port 8000│  │port 8000│  │port 8000│            │
│  └────┬────┘  └────┬────┘  └────┬────┘            │
│       └─────────────┼─────────────┘                 │
│                     │  shared SQLite WAL            │
│                     ▼                               │
│  ┌─────────────────────────────────────┐            │
│  │ backend/.cache/search_cache.sqlite  │            │
│  │ backend/.cache/budget_state         │            │
│  └─────────────────────────────────────┘            │
└─────────────────────────────────────────────────────┘
         │
         │  HTTPS (Caddy/Nginx reverse proxy)
         ▼
   ┌──────────┐
   │ Frontend │  React + TypeScript (Vite build → static)
   │  :5173   │
   └──────────┘
```

- **多 worker**: Gunicorn 起 N 个 Uvicorn worker,共享 SQLite WAL cache
- **代理预热**: lifespan 阶段 `get_proxy()` 后台探测,避免冷启动阻塞
- **Docker Compose**: R8 起 `docker-compose.yml` 一键起 backend + frontend

---

## 7. 测试策略

| 层 | 工具 | 覆盖 |
|----|------|------|
| 单元 | pytest | sanitize, budget atomicity, cache, refiner, decomposer |
| 集成 | pytest + httpx | API parsing, CORS hardening, request_id propagation |
| 静态扫描 | `python -c "import ..."` | 源级 marker 检测 (e.g. `get_cached_async(..., provider=)` 字面量存在) |
| 浏览器 | Playwright | 真实 LLM E2E + 截图验证 (R4) |

`pytest` 默认跑 27+ 测试,全过才允许 commit (CI: `.github/workflows/ci.yml`)。

---

## 8. 已知限制与 R11+ 计划

| 项 | 状态 | 备注 |
|----|------|------|
| aiosqlite 替换同步 SQLite | R8 文档化, R11+ 计划 | 跟 K8s 多 worker + SQLAlchemy 2.0 一起上 |
| sentence-transformers 真 embedding | R11+ 计划 | 当前 numpy 近似 |
| /search/stream 移动端响应式 | 不做 | 桌面优先研究工具 |
| Mock 中文论文 URL 404 | 不修 | 离线演示,已知边界 |
| 真实 E2E 自动化 | R11+ | 需 MiniMax API key + 浏览器自动化环境 |

---

**维护**: 任何架构变更 (新节点 / 新字段 / 新 ADR) 必须同步更新本文档 + `CHANGELOG.md`。
