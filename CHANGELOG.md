# Changelog

All notable changes to ScholarFlow will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **ENVIRONMENT 模式 (dev / test / prod)** — 后端按环境分档限流 + DB 目录隔离, 解决"开发 5/min 20/hour 太严"+"不知道开发/正式怎么区分"两条用户反馈
  - `dev` (默认): `/search` **30/min · 200/hour**, `/search/stream` 60/min · 500/hour, dev 友好
  - `test`: 1000/min, pytest/CI 不撞限流
  - `prod`: 5/min · 20/hour (旧值保留, 严格防滥用)
  - 别名兼容: `development`/`dev`、`testing`/`test`、`production`/`prod`, 未知值兜底 `dev`
- **SCHOLARFLOW_DB_DIR env** — 测试模式默认 `/tmp` (Windows `%TEMP%`), 强制隔离, 跑测试不污染 dev 缓存

### Changed
- `backend/config.py` — 6 处 `@limiter.limit` 改读 `_config.RATE_LIMITS_CURRENT[...]`, 不再硬编码
- `backend/api/routes/auth.py` — 新增 `_parse_limit_string` 辅助解析 "30/minute;200/hour" 风格
- `tests/conftest.py` — 强制 `ENVIRONMENT=test` + `SCHOLARFLOW_DB_DIR=tmp`, pytest 默认隔离
- `scholarflow.py` — `start_local` / `start_docker` 透传 `ENVIRONMENT` 给子进程; `status` 页加 "Mode / DB dir / Rate limit" 三行
- `.env.example` — 新增 `ENVIRONMENT=dev` 段 + `SCHOLARFLOW_DB_DIR` 注释
- `README.md` — 新增"🎚 运行模式"章节: 三档对照表 + 切换命令 + pytest 默认

### Tests
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
