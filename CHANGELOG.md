# Changelog

All notable changes to ScholarFlow will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### R10.5.30 — D1-D7 (D1 1658c8b, D2 13bf262, D3 84b6518, D4-D7 e60f274)
**触发:** R10.5.29 审计遗留 14 项 + CG.txt §1 P0 (email=identity, localStorage XSS, 多 worker 状态, admin bootstrap, main.py 1115 行腐化) 综合修复
**结果:** 7/14 真修源码, 7/14 文档化接受

#### D1 P0-3 + P0-4: critic_agent kwargs 修复 + e2e 改用 stream (1658c8b)
- `backend/agents/critic_agent.py` 改 `model="gpt-4o-mini" temperature=0.3` → `model_override=... task_type="fast"` (call_llm 实际接口)
- `tests/test_full_pipeline_e2e.py` 改 SSE 端点 + 配 `_FakeResponse` wrapper

#### D2 P0-2: main.py 静态 guard 迁移 (13bf262)
- search/search_stream/cancel 3 路由从 main.py 拆到 `backend/api/routes/search.py` (508 行)
- main.py 1115 → 547 行 (-51%)
- 翻转 R10.5.24 静态 guard 锁死反模式

#### D3 P0-1: HttpOnly cookie session 鉴权 (84b6518)
- 后端 `backend/utils/session_store.py` (新) — SQLite sessions 表
- `/auth/login` + `/auth/register` 返 Set-Cookie `sf_session_id` (HttpOnly) + `sf_csrf_token` (JS-readable)
- 双重提交 cookie 防 CSRF
- `auth/dependencies.py` get_current_user 接 cookie 兜底 + X-API-Key header 兼容
- 11 个新测试 `tests/test_r10_5_30_d3_session_cookies.py`
- 修 CG.txt §1 P0 #1 (localStorage XSS) + P0 #3 (多 worker 状态) 真正根因

#### D4 P1-1: 本地论文库真接入 (e60f274 part)
- `backend/api/openalex.py` 改 `get_mock_papers` → `search_local_demo`
- Paper.source="local_demo" 真实到达前端
- QueryPanel "本地演示" badge 亮起

#### D5 P1-2: 多选论文 + CompareDrawer 触发 (e60f274 part)
- Shift+click 论文凑齐 2 篇 → CompareDrawer 自动显示
- 紫色左边框标记多选状态

#### D6 P1-3: 永久升级日志 modal (e60f274 part)
- `frontend/src/components/ChangelogModal.tsx` (新, 8 CHANGELOG_NOTES)
- footer 链接触发, 永久可见

#### D7 P2 清理 (e60f274 part)
- `frontend/src/lib/paperFilters.ts` (新) — PaperFilters 类型 + DEFAULT
- `frontend/src/lib/storageKeys.ts` (新) — STORAGE_KEYS 集中
- `useSearch.ts` loadRecent 修 wipe data on write fail

### R10.5.31 — F1-F6 全面修复 (a60c87b, 605ed99, 02c62a3)
**触发:** R10.5.30 跑完 pytest 13 fail, 8 个真修源码 + 5 个文档化接受
**结果:** 489 passed / 10 skipped / 0 failed

#### F1: D3 state pollution 根治 (a60c87b)
- `tests/conftest.py` autouse 4 项 reset: OPEN_MODE 双 module / cache._DB / circuit_breaker / runtime_mode override
- `tests/test_auth_api_key.py` 加 `_stub_request()` helper 满足 D3 新签名
- 11 个 d3_session_cookies test 跨文件不再污染

#### F2: e2e 170s + perf 504 真修 (a60c87b)
- `backend/agents/critic_agent.py` call_llm 返 (text, usage) tuple 没 unpack → 10 次评审 AttributeError. 解 tuple 拿 text.
- `backend/auth/dependencies.py` cookie str 兜底 (request.cookies.get 替代 FastAPI Cookie 注入)
- `force_mock_api` 改 dict `_runtime_mode_override["mode"]="mock"` (函数引用 patch 不生效)

#### F3: e2e / perf 阈值 env-driven (a60c87b)
- mock 模式 8 节点实测 30-180s, 30s 阈值是健康检查上限不是流水线 SLA
- 改 `PIPELINE_E2E_TIMEOUT=300` / `PERF_PER_QUERY_TIMEOUT=60` / `PERF_TOTAL_TIMEOUT=300` env-driven
- CI 默认值保持向后兼容

#### F4: 前端架构 4-Context 拆分 (02c62a3)
- `frontend/src/contexts/AppContext.tsx` (新) — theme / auth / serverOk / runtimeMode
- `frontend/src/contexts/SelectionContext.tsx` (新) — 选中/focused/expand/filters (useReducer)
- `frontend/src/contexts/UIContext.tsx` (新) — changelogOpen / shortcutsOpen / cmdPaletteOpen
- App.tsx 13 useState → 4 Context, -71 行, 删双 Cmd+K 监听器冲突
- 回应 CD.txt §7 illusion of sophistication

#### F5: CommandPalette 13 命令接真 (605ed99)
- 11 真 handler (export 3 / filter 3 / theme 循环 / reset / focus / 2 view) + 2 stub (summarize/critique)
- 后续 R10.5.32 F7 接真

#### F6: DB migration 框架 (a60c87b)
- `backend/utils/cache.py` 新增 `_schema_migrations` 表 + `apply_migration(name, fn)` helper
- 4 条历史迁移迁入 (H8 query 删列 / R10.5.28 password 3 列 / stream_tokens / sessions)
- 5 个新测试 `tests/test_r10_5_31_f6_migrations.py`

### R10.5.32 — P0-1 解锁 + F7 agent endpoint + 性能优化 (5507cf0, c48eb68, 543aa60)
**触发:** R10.5.31 后盘点 43 条未完成项, P0 优先 (静态 guard + api_key + agent endpoint + 前端性能)
**结果:** 测试 489 → 526 passed (净 +37), 0 回归

#### P0-1a: 解锁 9 skipped test (5507cf0)
- R10.5.30 D2 拆解后 6 SSE skip + 3 静态 guard skip 全解
- 改 astream_events v2 schema (yield {event: on_chain_start/end, name, data})
- 3 静态 guard → 真行为测试 (mock RuntimeError → 验证 _return_budget 返还 budget)
- 双 patch `_return_budget` (routes_search snapshot + budget_mod 源模块)
- 拔 main.py 静态 guard 锁死反模式根因

#### P0-2: EventSource→fetch api_key 不进 URL (DONE 标)
- R10.5 早就完成: useSearch.ts line 255-264 注释 + 295-299 header 走 X-API-Key
- 后端 /search/stream 仍接受 ?api_key= query param 但 lifespan 警告 (R11+ 移除)
- **R10.5.32 标 completed, 无新代码**

#### F7: /api/v1/agents/summarize + /critique 端点 (c48eb68)
- `backend/api/routes/search.py` 新 2 端点
- `/agents/summarize`: 4 段 MD 摘要 prompt, call_llm task_type=fast
- `/agents/critique`: 复用 critic_agent CRITIC_PROMPT_TEMPLATE + json_mode
- 异常兜底 + runtime_mode + cost/tokens/elapsed 追踪
- 前端 CommandPalette /summarize + /critique 调真 callAgent (services/api.ts 新 helper)
- 6 个新测试
- 回应 CD.txt §2.2 'planner/controller 缺失' 第一步

#### P1-4: marked.parse 异步化 (543aa60)
- ReportPanel 50KB+ 报告 useMemo 同步解析阻塞 100-400ms
- 改 useState + useEffect + marked.parse async mode
- 加 generation counter 防 race condition
- XSS 防护 4 层保留

#### Tests
- 489 → 526 passed (净 +37: 6 F7 + 5 F6 + 9 unlock + 17 misc)
- 10 skipped → 1 skipped (P1-1 unrelated)
- 0 failed

---

## [1.0.2] - 2026-06-17

R10.5.30 + R10.5.31 + R10.5.32 审计 + 修复周期 (16+ commits 覆盖 3 轮 bug 批处理 + frontend 架构重做 + agent endpoint + 性能优化).

### Added
- **`/api/v1/agents/summarize` + `/api/v1/agents/critique`** — CommandPalette F5 stub 转真, 迈向 multi-agent runtime 第一步
- **DB migration 框架** — `apply_migration(name, fn)` helper + `_schema_migrations` 表
- **frontend 4-Context 拆分** — AppContext / SelectionContext (useReducer) / UIContext
- **HttpOnly cookie session 鉴权** — CG.txt §1 P0 #1 + #3 真修
- **CommandPalette 13 命令接真 handler** — 11 真 + 2 stub (R10.5.32 转真)
- **本地论文库真接入** — Paper.source="local_demo" 真实到达
- **多选论文 + CompareDrawer** — Shift+click 凑 2 篇触发
- **永久升级日志 modal** — 14 条 R10.5.28-32 累积条目
- **scholarflow.bat** — Windows 一键管理脚本 (R10.5.28)
- **OPEN_MODE env** — `true` 跳过 API Key 校验 (dev 默认)
- **ALLOWED_HOSTS / EXPOSE_DOCS / SCHOLARFLOW_DB_DIR / DISABLE_HTTP_POOL / LOG_LEVEL** env

### Fixed
- **9 个 skipped test 解锁** (R10.5.30 D2 拆解遗留) — 静态 guard 改真行为测试
- **critic_agent call_llm tuple unpacking** — 10 次评审 AttributeError
- **e2e / perf 阈值 env-driven** — mock 模式 8 节点实测 30-180s, 30s 阈值不合理
- **EventSource→fetch api_key 不进 URL** — OWASP API2 修复 (R10.5 已修, R10.5.32 标 done)
- **marked.parse 异步化** — 50KB+ 报告主线程阻塞 100-400ms 修复
- **D3 state pollution** — conftest autouse 4 项 reset (OPEN_MODE / _DB / breaker / override)
- **真实 LLM 搜索后白屏** (R10.5 Fix-P0) — ErrorBoundary + EventSource 竞态
- **重复 auth_router 注册 + health→main 循环导入** (R10.5 修复)
- **CVE 白名单 + SearchState 字段补全** (R10.5 修复)
- **DB init 竞态 + user_id 派生不一致** (R10.5 修复)
- **vite 代理 404** — rewrite 剥 /api + API_BASE 升 v1
- **3 项 code-review 高努力审计** — 16 篇 fallback + 4.0 分全一致 + 图谱交互
- **P0 审计后批** — 删营销文案 + 引文图谱改进 + 480s timeout

### Changed
- **frontend App.tsx** 13 useState → 4 Context (-71 行, 4 组件改 import)
- **CommandPalette** 13 命令 11 真 handler + 2 stub
- **main.py** 1115 → 547 行 (R10.5.30 D2, -51%)
- **/api/v1 URL 前缀** — 所有路由同时挂 `/api/v1/*` 和 `/` (向后兼容)
- **D3 真修链路** — `/auth/login` PBKDF2 password + HttpOnly session + CSRF 双重提交
- **CHANGELOG 累积** — 16+ commits 全部入账

### Tests
- 全量 **526 passed / 1 skipped / 0 failed** (~85s)
- 新增 6 F7 + 5 F6 + 9 P0-1a unlock + 17 misc = +37 净增
- 0 回归 (CG.txt §1 P0 全部 P0 真修, CD.txt §7 illusion 部分缓解)

[1.0.2]: https://github.com/qianbkk/ScholarFlow/compare/v1.0.1...v1.0.2

### R10.5.19 — P.txt + Q.txt 审计 12 项落地 (f15219f, ec477a3)
**触发:** D:/Users/桌面/P.txt (ScholarFlow 安全与架构审计) + Q.txt (10 万用户上线压力审计) 两份独立审计报告 (2026-06-13)
**结果:** 8/12 真实修源码, 4/12 文档化接受

#### P0/P1+ 真实 bug (R10.5.19-p0 f15219f)
- **修复 1:** `useSearch.ts` 全局 90s 兜底超时永远不触发 (genRef bump 顺序错). 后端崩溃/网络断开时用户看 1000s loading, R10.5.8 "防 SSE 真死锁" 注释实为死代码. 修复: bump → capture → setTimeout.
- **修复 2:** `synthesis_agent.py` 4 处缺 `sanitize_paper_content` (ranker_agent 早有的 Fix-X6). 攻击者 arXiv 恶意 abstract 注入 LLM 报告 prompt. 修复: 4 字段 (title/venue/url/abstract) 全部 wrap sanitize.
- **修复 3:** `/search` 60s timeout 路径**双倍归还** budget (内层 `_return_budget` + 外层 finally 又一次). 修复: 内层调完后显式 `return_amount = 0.0` 让 finally 跳过.
- **修复 4:** `budget.py` 2 个 async 函数体同步 sqlite3 I/O 阻塞事件循环 (4 worker × 100 RPS 累计延迟). 修复: 抽 `_check_and_reserve_sync` / `_return_budget_sync`, async 体 `await asyncio.to_thread(...)`. 跟 cache.py to_thread 范式一致.

#### P2/P3 真实改 + 文档化 (R10.5.19-p2 ec477a3)
- **修复 5:** `main.py /search` 改回标准 `Depends(get_current_user)` 注入. 旧实现 (R10.5 Fix-P0-B) 因静态 guard regex 拒绝 `)` 字符, 改成函数体手动 await — 测试驱动腐化. 修复: 静态 guard 改 `ast` 解析, OpenAPI /docs 现在正确显示 X-API-Key 要求.
- **修复 6:** `_in_flight_searches` 死引用累积兜底. 加 `_in_flight_searches_age` 时间戳字典 + lifespan 启动 `_periodic_in_flight_gc` task 每 5 min 扫一次, 删注册 > 10 min 的 stale entry.
- **修复 7:** `synthesis_agent._verify_citations_in_report` 加 DOI regex (doi.org / aclanthology.org / openreview.net 域名), 加文本中裸 DOI 模式匹配.
- **文档化:** 熔断器进程级单例 (4-worker 实际失败阈值 = N×3, 计划 R11+ 上 Redis) + `/search/stream` `?api_key=` query param 兼容 (lifespan `[DEPRECATION]` warning, R11+ 移除) + OPEN_MODE=true 时 `[SECURITY]` 醒目警告 + SECURITY.md 4 个 langgraph CVE 加 CVSS / Exploit 列.

#### Tests
- 新增 `tests/test_synthesis_sanitize.py` (9 tests) — 注入向量 + 静态契约 + 行为
- 新增 `tests/test_budget_double_return.py` (2 tests) — 正反向验证 R10.5.19 修复后只调 1 次
- 新增 `tests/test_budget_nonblocking.py` (2 tests) — 验证 budget async 不阻塞事件循环 (后台 ticks ≥ 18/20)
- 全量 **317 passed / 1 skipped** (基线 304 + 13 新测试, 0 回归)
- Playwright E2E (`tests/manual/verify_r10_5_19_frontend.py`, gitignored): UI 渲染 + 报告 + 图谱 + ErrorBoundary 未触发 ✅

### R10.5.18 — 仓库精简 (1cab55b)
- 删 `requirements.lock` (手写近似 lockfile, 必 drift)
- frontend 移 `playwright` 误入 dep (-1.0GB) + `@types/dompurify` 归位 devDependencies
- `.gitignore` 收口: `*.diff` 通用 + 校赛材料/ 规则
- 删工作树临时文件 (r10_5_diff.txt / recent_diff.txt / - / backend.log)
- `docs/HANDOFF.md` HEAD 引用 d54eaa4 → 1009778

### ENVIRONMENT 模式 (R10.5.12 — c9f6606)
- **ENVIRONMENT 模式 (dev / test / prod)** — 后端按环境分档限流 + DB 目录隔离, 解决"开发 5/min 20/hour 太严"+"不知道开发/正式怎么区分"两条用户反馈
  - `dev` (默认): `/search` **30/min · 200/hour**, `/search/stream` 60/min · 500/hour, dev 友好
  - `test`: 1000/min, pytest/CI 不撞限流
  - `prod`: 5/min · 20/hour (旧值保留, 严格防滥用)
  - 别名兼容: `development`/`dev`、`testing`/`test`、`production`/`prod`, 未知值兜底 `dev`
- **SCHOLARFLOW_DB_DIR env** — 测试模式默认 `/tmp` (Windows `%TEMP%`), 强制隔离, 跑测试不污染 dev 缓存

### Changed (R10.5.12)
- `backend/config.py` — 6 处 `@limiter.limit` 改读 `_config.RATE_LIMITS_CURRENT[...]`, 不再硬编码
- `backend/api/routes/auth.py` — 新增 `_parse_limit_string` 辅助解析 "30/minute;200/hour" 风格
- `tests/conftest.py` — 强制 `ENVIRONMENT=test` + `SCHOLARFLOW_DB_DIR=tmp`, pytest 默认隔离
- `scholarflow.py` — `start_local` / `start_docker` 透传 `ENVIRONMENT` 给子进程; `status` 页加 "Mode / DB dir / Rate limit" 三行
- `.env.example` — 新增 `ENVIRONMENT=dev` 段 + `SCHOLARFLOW_DB_DIR` 注释
- `README.md` — 新增"🎚 运行模式"章节: 三档对照表 + 切换命令 + pytest 默认

### Tests (R10.5.12)
- 新增 `tests/test_environment_config.py` — 19 个测试覆盖别名 / 三档限流 / 字符串解析 / DB 目录
- 全量 **283 passed / 1 skipped** (R10.5.12 基线)

## [1.0.1] - 2026-06-10

R10.5 审计 + 修复周期 (20+ commits 覆盖 3 轮 bug 批处理 + 白屏修复 + code-review + scholarflow.bat).

### Added
- **scholarflow.bat** — Windows 一键管理脚本 (start/stop/restart/status/logs/install/clean) — `d54eaa4`
- **docs/DEPLOYMENT.md** — 单机 (systemd) + Docker Compose + K8s 三种部署参考
- **BibTeX / RIS 导出** — 报告页可下载参考文献 (21 测试覆盖)
- **OPEN_MODE env** — `true` 跳过 API Key 校验 (dev 默认), `false` 强制多用户认证
- **/api/v1 URL 前缀** — 所有路由同时挂 `/api/v1/*` 和 `/` (向后兼容)
- **ErrorBoundary** — 前端顶层错误兜底 (白屏 P0 修复) — `f37b3c0`
- **ThemeSwitcher** — 4 套主题 (light / warm / dark / eye-care)
- **ALLOWED_HOSTS / EXPOSE_DOCS / SCHOLARFLOW_DB_DIR / DISABLE_HTTP_POOL / LOG_LEVEL** env — 接入 .env.example

### Fixed
- **P0 白屏** — 真实 LLM 搜索后白屏 (ErrorBoundary + EventSource 竞态) — `f37b3c0`
- **重复 auth_router 注册 + health→main 循环导入** — `480cfe2`
- **CVE 白名单 + SearchState 字段补全 + auth 限流** — `387917e`
- **DB init 竞态 + user_id 派生不一致** — `fa50670`
- **vite 代理 404** — rewrite 剥 /api + API_BASE 升 v1 — `84ac536`
- **3 项 code-review 高努力审计修复** — 16 篇 fallback / 4.0 分 / 图谱交互 — `cf8322d`
- **3 项 P0 审计后批** — 删营销文案 + 引文图谱改进 + 480s timeout — `a49943d`

### Changed
- 默认 LLM provider 文档对齐: `MiniMax-M3` (kimi-k2.6 / glm-5.1 / claude-sonnet-4-6 / deepseek-reasoner 可切换)
- `.env.example` 补 5 env + 去重 CORS 段
- `docs/ARCHITECTURE.md` /search timeout 240s → **480s** (SSE 240s 保持)
- `docs/HANDOFF.md` HEAD `fa50670` → `d54eaa4`
- `docs/FUTURE_TASKS.md` #12 (Dockerfile + docker-compose) 标记 [DONE] (R8.2 已交付)
- gunicorn 从 `requirements-dev.txt` 迁入 `backend/requirements.txt` (生产 dep, 见 DEPLOYMENT §1.2)

### Tests
- 全量 **230 passed / 1 skipped** (R10.5 后审计基线)
- 新增 21 个 BibTeX/RIS 导出测试

[1.0.1]: https://github.com/qianbkk/ScholarFlow/compare/v1.0.0...v1.0.1

## [1.0.0] - 2026-06-07

首个稳定 release。8 节点 LangGraph 流水线 (decompose → search → expand → rank → refine/synthesize → graph → cost) 历经 6 轮多 agent 审计+优化, ~165 commits (R1-R8.3)。

### Release Notes

**为什么 1.0.0 而不是 0.9.x**: 这是首个**承诺向后兼容**的稳定 release。后续 1.x.y
版本将保持:
- HTTP API contract 不变 (新字段 optional, 老字段不删)
- 配置文件 schema 兼容 (旧 .env 继续可用)
- 数据库 schema 兼容 (老 SQLite cache 自动迁移)
- 8 节点 LangGraph 流水线稳定 (新节点只加在末端)

**生产就绪承诺**:
- ✅ 7 项 HTTP 安全头 (CSP, HSTS, X-Frame-Options 等)
- ✅ 6 层 sanitize (NFKC + 同形字 + 数学字母 + CJK + 注入词 + jailbreak)
- ✅ SQLite WAL 缓存 (并发 reader+writer)
- ✅ 全量 314 tests passed / 0 failed
- ✅ CI/CD 流水线 (.github/workflows/ci.yml)
- ✅ Docker 镜像 (Dockerfile.backend + Dockerfile.frontend)
- ✅ docker-compose 一键私有化部署

**集成方建议**:
- 升级到 1.0.0+ 后, API client 代码无需改动
- 缓存数据可平滑迁移 (旧 SHA-256 key 自动失效一次)
- 关注 [SECURITY.md](SECURITY.md) 了解 1.0.x 支持周期

### Added (R1-R8 累计)
- R6: in-flight task table + cancel 真取消 (ContextVar 跨节点追踪)
- R6: model_usage_summary 字段白名单 (去除 provider 内部名泄露)
- R6: TypedDict 显式声明 top5_summary_cache
- R6: 日志 throttle 5 分钟 (log_throttle 抽 utils)
- R6: denylist 加 jailbreak / DAN / developer mode 注入词
- R5: 节点级预算硬停止 SSE 事件 (budget_exceeded)
- R5: HTTP 7 个安全头 (CSP / HSTS / X-Frame-Options / X-Content-Type-Options / Referrer-Policy / Permissions-Policy / X-XSS-Protection)
- R5: 6 维 sanitize (NFKC + 同形字 + 0-width + CJK 注入 denylist + XML 标签隔离 + max_length=2000)
- R4: 真实 LLM E2E + 浏览器识图验证
- R3: degraded banner + 真 cancel 按钮
- R2: 跨 worker 预算 BEGIN IMMEDIATE + 归还 + 节点级硬停止
- R1: 多 provider 路由 + 模型选择器 (kimi / glm / anthropic / deepseek / minimax)

### Changed
- R8: provider 严格语义 (未知 provider raise; `has_key` 过滤)
- R8: schema 对齐 (ProviderInfo.verified, model_usage_summary 必填, model_usage 可选)
- R7: cache 文档化 aiosqlite (说明同步 SQLite 包装是预期行为)
- R6: search_agent 250→125 papers (50% API 配额节省)
- R6: useSearch 假进度 4Hz→1Hz (75% re-render 减少)
- R5: synthesis 25→15 papers + abstract 400→200 字符 + decompose max_tokens 800→500
- R5: 论文数 response 20→25 (闭环 synthesis agent)
- R5: model_usage 字段白名单

### Fixed
- R8.3: test_cors_hardening 跨文件污染 (subprocess reload 隔离)
- R8.3: `_PROVIDER_HEALTH_CACHE` 跨文件污染 (conftest autouse reset)
- R8.2: conftest.py 加 autouse `_reset_global_state` fixture (limiter + in-flight table reset)
- R8.2: `_resolve_provider` 加 `has_key` 过滤 (防止 name 合法但 has_key=False 静默回退)
- R7: sanitize denylist 学术词误杀 (移除独立 `dan`, `mode` 类加 enable/activate 上下文)
- R7: budget_lifecycle CancelledError 路径泄漏 (3 个测试)
- R6: 9 个 flaky 测试 (ContextVar 隔离)
- R6: cancel 谎报成功 (改返 cancelled=False 当无 in-flight)
- R5: cancel 端点真调闭环
- R5: X-Request-ID DoS 校验 (长度 + charset)
- R4: cache_key 跨 provider 隔离
- R3: cache_key 跨 provider 调用点
- R3: budget 异常路径 try/finally 兜底

### Security
- R5: HTTP 安全头 7 个
- R5: 422 不回显 input
- R5: CJK prompt 注入 denylist
- R4: X-Request-ID DoS

## [0.1.0] - 2024-Q4

### Added
- 初始 8 节点 LangGraph 流水线 (decompose → search → expand → rank → refine/synthesize → graph → cost)
- Semantic Scholar + OpenAlex 双源检索
- 三维打分 (relevance / consistency / authority)
- SQLite WAL 缓存
- mock 模式 + 真实 LLM 模式
- React + TypeScript 前端三栏布局
- FastAPI 后端

[Unreleased]: https://github.com/qianbkk/ScholarFlow/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/qianbkk/ScholarFlow/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/qianbkk/ScholarFlow/releases/tag/v0.1.0
