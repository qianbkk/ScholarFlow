# Changelog

All notable changes to ScholarFlow will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-06-07

首个稳定 release。8 节点 LangGraph 流水线 (decompose → search → expand → rank → refine/synthesize → graph → cost) 历经 6 轮多 agent 审计+优化, ~165 commits (R1-R8.3)。

### Added
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
